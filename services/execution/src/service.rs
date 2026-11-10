//! Order handling: idempotency, risk checks, broker routing, and the transactional ledger update.

use std::sync::Arc;

use chrono::Utc;
use rust_decimal::Decimal;
use serde::{Deserialize, Serialize};
use sqlx::{postgres::PgRow, PgPool, Postgres, Row, Transaction};
use uuid::Uuid;

use crate::broker::{Broker, BrokerLookup, OrderRequest, StillPending};
use crate::risk::{self, Inputs, Profile, Side, COOLDOWN_MINUTES};

#[derive(Debug, Deserialize)]
pub struct NewOrder {
    pub signal_id: Uuid,
    pub bot_slug: String,
    pub symbol: String,
    pub side: String,
    pub target_pct: Decimal,
    pub idempotency_key: String,
}

#[derive(Debug, Serialize, PartialEq)]
pub struct OrderRecord {
    pub id: Uuid,
    pub signal_id: Uuid,
    pub bot_slug: String,
    pub symbol: String,
    pub side: String,
    pub qty: Decimal,
    pub status: String,
    pub reject_reason: Option<String>,
    pub fill_price: Option<Decimal>,
    pub broker: String,
    pub latency_ms: Option<i32>,
}

/// Everything needed to book one fill.
pub struct FillRequest<'a> {
    pub order_id: Uuid,
    pub bot_id: i32,
    pub symbol: &'a str,
    pub side: Side,
    pub qty: Decimal,
    pub price: Decimal,
    pub broker_order_id: Option<String>,
}

#[derive(Debug)]
pub enum ServiceError {
    BadRequest(String),
    Internal(String),
}

impl From<sqlx::Error> for ServiceError {
    fn from(e: sqlx::Error) -> Self {
        ServiceError::Internal(e.to_string())
    }
}

pub struct Service {
    pub pool: PgPool,
    pub sim: Arc<dyn Broker>,
    pub alpaca: Option<Arc<dyn Broker>>,
    pub force_market_open: bool,
}

const ORDER_SELECT: &str =
    "SELECT o.id, o.signal_id, b.slug AS bot_slug, o.symbol, o.side, o.qty, o.status,
    o.reject_reason, o.broker, o.latency_ms,
    (SELECT price FROM fills f WHERE f.order_id = o.id ORDER BY filled_at LIMIT 1) AS fill_price
    FROM orders o JOIN bots b ON b.id = o.bot_id";

/// A numeric setting from a bot's params. JSON numbers are read through their text so 0.2 stays exactly 0.2.
fn param(params: &serde_json::Value, key: &str) -> Option<Decimal> {
    params[key]
        .as_f64()
        .and_then(|_| params[key].to_string().parse().ok())
}

fn record(r: &PgRow) -> OrderRecord {
    OrderRecord {
        id: r.get("id"),
        signal_id: r.get("signal_id"),
        bot_slug: r.get("bot_slug"),
        symbol: r.get("symbol"),
        side: r.get("side"),
        qty: r.get("qty"),
        status: r.get("status"),
        reject_reason: r.get("reject_reason"),
        fill_price: r.get("fill_price"),
        broker: r.get("broker"),
        latency_ms: r.get("latency_ms"),
    }
}

impl Service {
    pub async fn get_order(&self, id: Uuid) -> Result<Option<OrderRecord>, ServiceError> {
        let row = sqlx::query(&format!("{ORDER_SELECT} WHERE o.id = $1"))
            .bind(id)
            .fetch_optional(&self.pool)
            .await?;
        Ok(row.as_ref().map(record))
    }

    async fn existing(
        &self,
        key: &str,
        signal_id: Uuid,
    ) -> Result<Option<OrderRecord>, ServiceError> {
        let row = sqlx::query(&format!(
            "{ORDER_SELECT} WHERE o.idempotency_key = $1 OR o.signal_id = $2"
        ))
        .bind(key)
        .bind(signal_id)
        .fetch_optional(&self.pool)
        .await?;
        Ok(row.as_ref().map(record))
    }

    pub async fn place(&self, req: NewOrder) -> Result<OrderRecord, ServiceError> {
        let side = Side::parse(&req.side)
            .ok_or_else(|| ServiceError::BadRequest("side must be BUY or SELL".into()))?;
        if req.idempotency_key.is_empty() {
            return Err(ServiceError::BadRequest("idempotency_key required".into()));
        }
        if let Some(found) = self.existing(&req.idempotency_key, req.signal_id).await? {
            return Ok(found);
        }
        let bot = sqlx::query("SELECT id, broker, params FROM bots WHERE slug = $1")
            .bind(&req.bot_slug)
            .fetch_optional(&self.pool)
            .await?
            .ok_or_else(|| ServiceError::BadRequest(format!("unknown bot {}", req.bot_slug)))?;
        let bot_id: i32 = bot.get("id");
        let params: serde_json::Value = bot.get("params");
        let allow_short = params["allow_short"] == true;
        let max_pct = risk::position_cap(param(&params, "max_position_pct"));
        let daily_loss_limit = param(&params, "daily_loss_limit").unwrap_or_default();
        let max_drawdown = param(&params, "max_drawdown").unwrap_or_default();
        let profile = if params["risk_profile"] == "benchmark" {
            Profile::Benchmark
        } else {
            Profile::Standard
        };
        let broker: Arc<dyn Broker> = match (bot.get::<String, _>("broker").as_str(), &self.alpaca)
        {
            ("alpaca_paper", Some(b)) => b.clone(),
            _ => self.sim.clone(), // no Alpaca keys configured: fall back to the simulator
        };
        let is_crypto = req.symbol.contains('/');

        let mut tx = self.pool.begin().await?;
        // Per-bot lock: serialises risk checks for one bot.
        let cash: Decimal =
            sqlx::query_scalar("SELECT amount FROM cash WHERE bot_id = $1 FOR UPDATE")
                .bind(bot_id)
                .fetch_optional(&mut *tx)
                .await?
                .ok_or_else(|| ServiceError::BadRequest("bot has no cash row".into()))?;
        if let Some(found) = self.existing(&req.idempotency_key, req.signal_id).await? {
            return Ok(found); // lost a race with an identical request
        }
        let price = latest_price(&mut tx, &req.symbol).await?;
        let positions = sqlx::query(
            "SELECT symbol, qty, avg_cost FROM positions WHERE bot_id = $1 AND qty <> 0",
        )
        .bind(bot_id)
        .fetch_all(&mut *tx)
        .await?;
        let mut equity = cash;
        let mut held = Decimal::ZERO;
        let mut short_exposure = Decimal::ZERO;
        for p in &positions {
            let sym: String = p.get("symbol");
            let qty: Decimal = p.get("qty");
            if sym == req.symbol {
                held = qty;
            }
            let px = latest_price(&mut tx, &sym)
                .await?
                .unwrap_or_else(|| p.get("avg_cost"));
            equity += qty * px; // a short has negative qty, so it subtracts its current cost to buy back
            if qty < Decimal::ZERO {
                short_exposure += -qty * px;
            }
        }
        let in_cooldown: bool = sqlx::query_scalar(
            "SELECT EXISTS (SELECT 1 FROM orders WHERE bot_id=$1 AND symbol=$2 AND status IN ('submitted','filled')
             AND submitted_at > now() - make_interval(mins => $3))",
        )
        .bind(bot_id)
        .bind(&req.symbol)
        .bind(COOLDOWN_MINUTES as i32)
        .fetch_one(&mut *tx)
        .await?;
        let already_bought_once: bool = sqlx::query_scalar(
            "SELECT EXISTS (SELECT 1 FROM orders WHERE bot_id=$1 AND side='BUY' AND status IN ('submitted','filled'))",
        )
        .bind(bot_id)
        .fetch_one(&mut *tx)
        .await?;

        // Yesterday's last snapshot is today's starting line; the highest snapshot ever is the peak.
        let day_start_equity: Option<Decimal> = sqlx::query_scalar(
            "SELECT equity FROM equity_snapshots WHERE bot_id=$1 AND ts < $2 ORDER BY ts DESC LIMIT 1",
        )
        .bind(bot_id)
        .bind(risk::et_day_start(Utc::now()))
        .fetch_optional(&mut *tx)
        .await?;
        let peak_equity: Option<Decimal> =
            sqlx::query_scalar("SELECT max(equity) FROM equity_snapshots WHERE bot_id=$1")
                .bind(bot_id)
                .fetch_one(&mut *tx)
                .await?;

        let decision = match price {
            None => Err("no price available".to_string()),
            Some(price) => risk::size_order(&Inputs {
                profile,
                side,
                is_crypto,
                market_open: self.force_market_open || risk::equity_market_open(Utc::now()),
                equity,
                cash,
                open_positions: positions.len(),
                held_qty: held,
                allow_short,
                short_exposure,
                target_pct: req.target_pct,
                price,
                in_cooldown,
                already_bought_once,
                max_pct,
                day_start_equity,
                peak_equity,
                daily_loss_limit,
                max_drawdown,
            })
            .map(|q| (q, price)),
        };

        let order_id = Uuid::new_v4();
        let (status, qty, reason) = match &decision {
            Ok((q, _)) => ("submitted", *q, None),
            Err(why) => ("rejected", Decimal::ZERO, Some(why.clone())),
        };
        let inserted = sqlx::query(
            "INSERT INTO orders (id, signal_id, bot_id, symbol, side, qty, idempotency_key, broker, status,
                reject_reason, latency_ms)
             SELECT $1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                    GREATEST(0, (extract(epoch FROM now() - s.created_at) * 1000)::int)
             FROM signals s WHERE s.id = $2
             ON CONFLICT DO NOTHING RETURNING id",
        )
        .bind(order_id)
        .bind(req.signal_id)
        .bind(bot_id)
        .bind(&req.symbol)
        .bind(side.as_str())
        .bind(qty)
        .bind(&req.idempotency_key)
        .bind(broker.name())
        .bind(status)
        .bind(&reason)
        .fetch_optional(&mut *tx)
        .await?;
        if inserted.is_none() {
            tx.rollback().await?;
            return self
                .existing(&req.idempotency_key, req.signal_id)
                .await?
                .ok_or_else(|| ServiceError::BadRequest("unknown signal_id".into()));
        }
        tx.commit().await?;

        if let Ok((qty, ref_price)) = decision {
            let client_order_id = order_id.to_string();
            let outcome = broker
                .execute(&OrderRequest {
                    client_order_id: &client_order_id,
                    symbol: &req.symbol,
                    side,
                    qty,
                    ref_price,
                    is_crypto,
                })
                .await;
            let applied = match outcome {
                Ok(fill) => {
                    self.apply_fill(FillRequest {
                        order_id,
                        bot_id,
                        symbol: &req.symbol,
                        side,
                        qty,
                        price: fill.price,
                        broker_order_id: fill.broker_order_id,
                    })
                    .await
                }
                // The broker may still fill this order. Leave it `submitted`; reconcile_stale settles it.
                Err(e) if e.downcast_ref::<StillPending>().is_some() => {
                    tracing::warn!(%order_id, "{e}; left submitted for reconciliation");
                    return self
                        .get_order(order_id)
                        .await?
                        .ok_or_else(|| ServiceError::Internal("order vanished".into()));
                }
                Err(e) => Err(ServiceError::Internal(e.to_string())),
            };
            if let Err(ServiceError::Internal(msg) | ServiceError::BadRequest(msg)) = applied {
                sqlx::query("UPDATE orders SET status='rejected', reject_reason=$2, updated_at=now() WHERE id=$1 AND status='submitted'")
                    .bind(order_id)
                    .bind(format!("broker: {msg}"))
                    .execute(&self.pool)
                    .await?;
            }
        }
        self.get_order(order_id)
            .await?
            .ok_or_else(|| ServiceError::Internal("order vanished".into()))
    }

    /// Fill, position and cash change in one transaction; any failure rolls everything back.
    pub async fn apply_fill(&self, f: FillRequest<'_>) -> Result<(), ServiceError> {
        let FillRequest {
            order_id,
            bot_id,
            symbol,
            side,
            qty,
            price,
            broker_order_id,
        } = f;
        let mut tx = self.pool.begin().await?;
        // Book a fill once: the request handler and the reconciler can both try for the same order.
        let status: Option<String> =
            sqlx::query_scalar("SELECT status FROM orders WHERE id=$1 FOR UPDATE")
                .bind(order_id)
                .fetch_optional(&mut *tx)
                .await?;
        if status.as_deref() != Some("submitted") {
            return Err(ServiceError::BadRequest(
                "order is not awaiting a fill".into(),
            ));
        }
        let cash: Decimal =
            sqlx::query_scalar("SELECT amount FROM cash WHERE bot_id=$1 FOR UPDATE")
                .bind(bot_id)
                .fetch_one(&mut *tx)
                .await?;
        let notional = qty * price;
        sqlx::query("INSERT INTO fills (id, order_id, qty, price) VALUES ($1,$2,$3,$4)")
            .bind(Uuid::new_v4())
            .bind(order_id)
            .bind(qty)
            .bind(price)
            .execute(&mut *tx)
            .await?;
        let new_cash = match side {
            Side::Buy => {
                if notional > cash {
                    return Err(ServiceError::BadRequest("insufficient cash at fill".into()));
                }
                sqlx::query(
                    "INSERT INTO positions (bot_id, symbol, qty, avg_cost) VALUES ($1,$2,$3,$4)
                     ON CONFLICT (bot_id, symbol) DO UPDATE SET
                       avg_cost = (positions.qty * positions.avg_cost + EXCLUDED.qty * EXCLUDED.avg_cost)
                                  / (positions.qty + EXCLUDED.qty),
                       qty = positions.qty + EXCLUDED.qty",
                )
                .bind(bot_id)
                .bind(symbol)
                .bind(qty)
                .bind(price)
                .execute(&mut *tx)
                .await?;
                cash - notional
            }
            Side::Sell => {
                let held: Option<Decimal> = sqlx::query_scalar(
                    "SELECT qty FROM positions WHERE bot_id=$1 AND symbol=$2 FOR UPDATE",
                )
                .bind(bot_id)
                .bind(symbol)
                .fetch_optional(&mut *tx)
                .await?;
                if held.unwrap_or_default() < qty {
                    return Err(ServiceError::BadRequest(
                        "position smaller than sell quantity".into(),
                    ));
                }
                sqlx::query("DELETE FROM positions WHERE bot_id=$1 AND symbol=$2 AND qty <= $3")
                    .bind(bot_id)
                    .bind(symbol)
                    .bind(qty)
                    .execute(&mut *tx)
                    .await?;
                cash + notional
            }
            Side::Short => {
                // The proceeds land in cash; the short is carried as a negative position at its entry price.
                let existing: Option<Decimal> = sqlx::query_scalar(
                    "SELECT qty FROM positions WHERE bot_id=$1 AND symbol=$2 FOR UPDATE",
                )
                .bind(bot_id)
                .bind(symbol)
                .fetch_optional(&mut *tx)
                .await?;
                if existing.is_some_and(|q| q != Decimal::ZERO) {
                    return Err(ServiceError::BadRequest(
                        "already holding this symbol".into(),
                    ));
                }
                sqlx::query(
                    "INSERT INTO positions (bot_id, symbol, qty, avg_cost) VALUES ($1,$2,$3,$4)
                     ON CONFLICT (bot_id, symbol) DO UPDATE SET qty = EXCLUDED.qty, avg_cost = EXCLUDED.avg_cost",
                )
                .bind(bot_id)
                .bind(symbol)
                .bind(-qty)
                .bind(price)
                .execute(&mut *tx)
                .await?;
                cash + notional
            }
            Side::Cover => {
                let held: Option<Decimal> = sqlx::query_scalar(
                    "SELECT qty FROM positions WHERE bot_id=$1 AND symbol=$2 FOR UPDATE",
                )
                .bind(bot_id)
                .bind(symbol)
                .fetch_optional(&mut *tx)
                .await?;
                if held.unwrap_or_default() > -qty {
                    return Err(ServiceError::BadRequest(
                        "short position smaller than cover quantity".into(),
                    ));
                }
                if notional > cash {
                    return Err(ServiceError::BadRequest("insufficient cash at fill".into()));
                }
                sqlx::query("DELETE FROM positions WHERE bot_id=$1 AND symbol=$2 AND qty >= -$3")
                    .bind(bot_id)
                    .bind(symbol)
                    .bind(qty)
                    .execute(&mut *tx)
                    .await?;
                cash - notional
            }
        };
        sqlx::query("UPDATE cash SET amount=$2 WHERE bot_id=$1")
            .bind(bot_id)
            .bind(new_cash)
            .execute(&mut *tx)
            .await?;
        sqlx::query(
            "UPDATE orders SET status='filled', broker_order_id=$2, updated_at=now() WHERE id=$1",
        )
        .bind(order_id)
        .bind(broker_order_id)
        .execute(&mut *tx)
        .await?;
        tx.commit().await?;
        Ok(())
    }

    /// Settle Alpaca orders whose outcome was lost (a timeout, a crash, a dropped connection) by asking Alpaca
    /// what happened to each one. Returns how many it settled.
    pub async fn reconcile_stale(&self) -> Result<usize, ServiceError> {
        let Some(alpaca) = &self.alpaca else {
            return Ok(0);
        };
        let rows = sqlx::query(
            "SELECT id, bot_id, symbol, side, qty FROM orders
             WHERE status = 'submitted' AND broker = 'alpaca_paper'
               AND submitted_at < now() - interval '5 minutes' ORDER BY submitted_at",
        )
        .fetch_all(&self.pool)
        .await?;
        let mut settled = 0;
        for r in rows {
            let id: Uuid = r.get("id");
            let symbol: String = r.get("symbol");
            let outcome = match alpaca.lookup(&id.to_string()).await {
                Ok(o) => o,
                Err(e) => {
                    tracing::warn!(%id, "reconcile lookup failed: {e}");
                    continue;
                }
            };
            match outcome {
                BrokerLookup::Filled(fill) => {
                    let Some(side) = Side::parse(&r.get::<String, _>("side")) else {
                        continue;
                    };
                    let applied = self
                        .apply_fill(FillRequest {
                            order_id: id,
                            bot_id: r.get("bot_id"),
                            symbol: &symbol,
                            side,
                            qty: r.get("qty"),
                            price: fill.price,
                            broker_order_id: fill.broker_order_id,
                        })
                        .await;
                    match applied {
                        Ok(()) => {
                            tracing::info!(%id, %symbol, "reconciled a lost fill");
                            settled += 1;
                        }
                        // Filled at the broker but cannot be booked. Leave it visible rather than hide it.
                        Err(e) => {
                            tracing::error!(%id, %symbol, "filled at broker, cannot book: {e:?}")
                        }
                    }
                }
                BrokerLookup::Dead(why) => {
                    sqlx::query(
                        "UPDATE orders SET status='rejected', reject_reason=$2, updated_at=now()
                         WHERE id=$1 AND status='submitted'",
                    )
                    .bind(id)
                    .bind(format!("broker: {why}"))
                    .execute(&self.pool)
                    .await?;
                    tracing::info!(%id, %symbol, "reconciled a dead order: {why}");
                    settled += 1;
                }
                BrokerLookup::Pending | BrokerLookup::Unsupported => {}
            }
        }
        Ok(settled)
    }

    pub async fn metrics_text(&self) -> Result<String, ServiceError> {
        let mut out = String::from("# TYPE arena_orders_total counter\n");
        for r in sqlx::query("SELECT status, count(*) AS n FROM orders GROUP BY status")
            .fetch_all(&self.pool)
            .await?
        {
            let (s, n): (String, i64) = (r.get("status"), r.get("n"));
            out.push_str(&format!("arena_orders_total{{status=\"{s}\"}} {n}\n"));
        }
        let q = sqlx::query(
            "SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY latency_ms)::float8 AS p50,
                    percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::float8 AS p95
             FROM orders WHERE latency_ms IS NOT NULL",
        )
        .fetch_one(&self.pool)
        .await?;
        let p50: Option<f64> = q.get("p50");
        let p95: Option<f64> = q.get("p95");
        out.push_str("# TYPE arena_signal_to_submit_ms gauge\n");
        out.push_str(&format!(
            "arena_signal_to_submit_ms{{quantile=\"0.5\"}} {}\n",
            p50.unwrap_or(0.0)
        ));
        out.push_str(&format!(
            "arena_signal_to_submit_ms{{quantile=\"0.95\"}} {}\n",
            p95.unwrap_or(0.0)
        ));
        Ok(out)
    }
}

async fn latest_price(
    tx: &mut Transaction<'_, Postgres>,
    symbol: &str,
) -> Result<Option<Decimal>, sqlx::Error> {
    sqlx::query_scalar("SELECT c FROM bars WHERE symbol=$1 AND timeframe IN ('1Min','5Min') ORDER BY ts DESC LIMIT 1")
        .bind(symbol)
        .fetch_optional(&mut **tx)
        .await
}
