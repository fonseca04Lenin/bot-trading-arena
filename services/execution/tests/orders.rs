//! Integration tests against a throwaway Postgres (TEST_DATABASE_URL, default arena_test on :5433).

use std::sync::Arc;

use arena_execution::{
    broker::{Broker, BrokerFill, BrokerLookup, OrderRequest, SimBroker, StillPending},
    http::{router, AppState},
    service::{FillRequest, NewOrder, Service},
};
use async_trait::async_trait;
use axum::{body::Body, http::Request};
use http_body_util::BodyExt;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;
use sqlx::{postgres::PgPoolOptions, PgPool, Row};
use tokio::sync::{Mutex, MutexGuard};
use tower::ServiceExt;
use uuid::Uuid;

static DB_LOCK: Mutex<()> = Mutex::const_new(());

struct Env {
    _guard: MutexGuard<'static, ()>,
    pool: PgPool,
    svc: Arc<Service>,
}

async fn setup() -> Env {
    let guard = DB_LOCK.lock().await;
    let url = std::env::var("TEST_DATABASE_URL")
        .unwrap_or("postgresql://arena@localhost:5433/arena_test".into());
    let pool = PgPoolOptions::new()
        .max_connections(5)
        .connect(&url)
        .await
        .unwrap();
    sqlx::query(
        "TRUNCATE fills, orders, signals, positions, cash, bars, bots RESTART IDENTITY CASCADE",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query(
        "INSERT INTO bots (slug,name,strategy_kind,params,starting_cash,broker) VALUES
         ('crossover','C','crossover','{}',100000,'sim'),
         ('index','I','index','{\"risk_profile\":\"benchmark\"}',100000,'sim')",
    )
    .execute(&pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO cash SELECT id, 100000 FROM bots")
        .execute(&pool)
        .await
        .unwrap();
    for sym in ["AAPL", "SPY", "BTC/USD"] {
        sqlx::query("INSERT INTO bars VALUES ($1,'1Min',now(),100,100,100,100,1)")
            .bind(sym)
            .execute(&pool)
            .await
            .unwrap();
    }
    let svc = Arc::new(Service {
        pool: pool.clone(),
        sim: Arc::new(SimBroker),
        alpaca: None,
        force_market_open: true,
    });
    Env {
        _guard: guard,
        pool,
        svc,
    }
}

async fn signal(pool: &PgPool, bot: &str, symbol: &str) -> Uuid {
    let id = Uuid::new_v4();
    sqlx::query(
        "INSERT INTO signals (id,bot_id,symbol,side,target_pct,rationale,bar_ts)
         SELECT $1, id, $3, 'BUY', 0.1, 'test', now() FROM bots WHERE slug=$2",
    )
    .bind(id)
    .bind(bot)
    .bind(symbol)
    .execute(pool)
    .await
    .unwrap();
    id
}

fn order(signal_id: Uuid, bot: &str, symbol: &str, side: &str, pct: Decimal) -> NewOrder {
    NewOrder {
        signal_id,
        bot_slug: bot.into(),
        symbol: symbol.into(),
        side: side.into(),
        target_pct: pct,
        idempotency_key: format!("sig-{signal_id}"),
    }
}

async fn cash(pool: &PgPool, bot: &str) -> Decimal {
    sqlx::query_scalar("SELECT amount FROM cash c JOIN bots b ON b.id=c.bot_id WHERE slug=$1")
        .bind(bot)
        .fetch_one(pool)
        .await
        .unwrap()
}

#[tokio::test]
async fn idempotent_same_key_gives_one_order() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let a = e
        .svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    let b = e
        .svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(a, b);
    assert_eq!(a.status, "filled");
    let n: i64 = sqlx::query_scalar("SELECT count(*) FROM orders")
        .fetch_one(&e.pool)
        .await
        .unwrap();
    assert_eq!(n, 1);
}

#[tokio::test]
async fn buy_fills_with_slippage_and_updates_cash_and_position() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.fill_price, Some(dec!(100.02)));
    assert_eq!(o.qty, dec!(99.9800));
    assert_eq!(
        cash(&e.pool, "crossover").await,
        dec!(100000) - o.qty * dec!(100.02)
    );
    let pos: Decimal = sqlx::query_scalar("SELECT qty FROM positions")
        .fetch_one(&e.pool)
        .await
        .unwrap();
    assert_eq!(pos, o.qty);
}

#[tokio::test]
async fn cooldown_rejects_a_second_buy_and_records_reason() {
    let e = setup().await;
    let s1 = signal(&e.pool, "crossover", "AAPL").await;
    e.svc
        .place(order(s1, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    let s2 = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s2, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.status, "rejected");
    assert!(o.reject_reason.unwrap().starts_with("cooldown"));
}

#[tokio::test]
async fn a_sell_right_after_a_buy_is_not_held_up_by_the_cooldown() {
    let e = setup().await;
    let s1 = signal(&e.pool, "crossover", "AAPL").await;
    e.svc
        .place(order(s1, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    let s2 = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s2, "crossover", "AAPL", "SELL", Decimal::ZERO))
        .await
        .unwrap();
    assert_eq!(o.status, "filled");
}

#[tokio::test]
async fn position_limit_is_five() {
    let e = setup().await;
    for sym in ["AAPL", "SPY", "BTC/USD"] {
        let s = signal(&e.pool, "crossover", sym).await;
        assert_eq!(
            e.svc
                .place(order(s, "crossover", sym, "BUY", dec!(0.1)))
                .await
                .unwrap()
                .status,
            "filled"
        );
    }
    for i in 0..2 {
        let sym = format!("X{i}");
        sqlx::query("INSERT INTO bars VALUES ($1,'1Min',now(),10,10,10,10,1)")
            .bind(&sym)
            .execute(&e.pool)
            .await
            .unwrap();
        let s = signal(&e.pool, "crossover", &sym).await;
        assert_eq!(
            e.svc
                .place(order(s, "crossover", &sym, "BUY", dec!(0.1)))
                .await
                .unwrap()
                .status,
            "filled"
        );
    }
    sqlx::query("INSERT INTO bars VALUES ('X9','1Min',now(),10,10,10,10,1)")
        .execute(&e.pool)
        .await
        .unwrap();
    let s = signal(&e.pool, "crossover", "X9").await;
    let o = e
        .svc
        .place(order(s, "crossover", "X9", "BUY", dec!(0.1)))
        .await
        .unwrap();
    assert_eq!(o.status, "rejected");
    assert!(o.reject_reason.unwrap().starts_with("position limit"));
}

#[tokio::test]
async fn benchmark_buys_all_cash_once() {
    let e = setup().await;
    let s = signal(&e.pool, "index", "SPY").await;
    let o = e
        .svc
        .place(order(s, "index", "SPY", "BUY", dec!(1.0)))
        .await
        .unwrap();
    assert_eq!(o.status, "filled");
    assert!(cash(&e.pool, "index").await < dec!(10));
    let s2 = signal(&e.pool, "index", "SPY").await;
    assert_eq!(
        e.svc
            .place(order(s2, "index", "SPY", "BUY", dec!(1.0)))
            .await
            .unwrap()
            .status,
        "rejected"
    );
}

#[tokio::test]
async fn failed_fill_leaves_no_partial_writes() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    let before = cash(&e.pool, "crossover").await;
    let bot_id: i32 = sqlx::query_scalar("SELECT id FROM bots WHERE slug='crossover'")
        .fetch_one(&e.pool)
        .await
        .unwrap();
    sqlx::query("UPDATE orders SET status='submitted' WHERE id=$1")
        .bind(o.id)
        .execute(&e.pool)
        .await
        .unwrap();
    // A fill larger than available cash must fail and roll back the fill row, position and cash.
    let res = e
        .svc
        .apply_fill(FillRequest {
            order_id: o.id,
            bot_id,
            symbol: "AAPL",
            side: arena_execution::risk::Side::Buy,
            qty: dec!(1000000),
            price: dec!(100),
            broker_order_id: None,
        })
        .await;
    assert!(res.is_err());
    assert_eq!(cash(&e.pool, "crossover").await, before);
    let fills: i64 = sqlx::query_scalar("SELECT count(*) FROM fills")
        .fetch_one(&e.pool)
        .await
        .unwrap();
    assert_eq!(fills, 1);
}

#[tokio::test]
async fn fills_reconcile_with_cash_and_positions() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    e.svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    let row = sqlx::query(
        "SELECT COALESCE(SUM(CASE WHEN o.side='BUY' THEN -f.qty*f.price ELSE f.qty*f.price END),0) AS net
         FROM fills f JOIN orders o ON o.id=f.order_id",
    )
    .fetch_one(&e.pool)
    .await
    .unwrap();
    let net: Decimal = row.get("net");
    assert_eq!(cash(&e.pool, "crossover").await, dec!(100000) + net);
}

async fn call(app: axum::Router, key: Option<&str>, body: &str) -> (u16, String) {
    let mut req = Request::post("/v1/orders").header("content-type", "application/json");
    if let Some(k) = key {
        req = req.header("x-arena-key", k);
    }
    let resp = app
        .oneshot(req.body(Body::from(body.to_string())).unwrap())
        .await
        .unwrap();
    let status = resp.status().as_u16();
    (
        status,
        String::from_utf8(
            resp.into_body()
                .collect()
                .await
                .unwrap()
                .to_bytes()
                .to_vec(),
        )
        .unwrap(),
    )
}

#[tokio::test]
async fn auth_header_required() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let app = router(AppState {
        svc: e.svc.clone(),
        arena_key: Arc::new("secret".into()),
    });
    let body = format!(
        r#"{{"signal_id":"{s}","bot_slug":"crossover","symbol":"AAPL","side":"BUY","target_pct":"0.10","idempotency_key":"k1"}}"#
    );
    assert_eq!(call(app.clone(), None, &body).await.0, 401);
    assert_eq!(call(app.clone(), Some("wrong"), &body).await.0, 401);
    let (code, text) = call(app.clone(), Some("secret"), &body).await;
    assert_eq!(code, 200, "{text}");
    let healthz = app
        .oneshot(Request::get("/healthz").body(Body::empty()).unwrap())
        .await
        .unwrap();
    assert_eq!(healthz.status(), 200);
}

#[tokio::test]
async fn metrics_report_orders_and_latency() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    e.svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    let text = e.svc.metrics_text().await.unwrap();
    assert!(text.contains("arena_orders_total{status=\"filled\"} 1"));
    assert!(text.contains("quantile=\"0.95\""));
}

#[derive(Clone, Copy)]
enum Look {
    Filled,
    Dead,
    Pending,
}

/// A stand-in for Alpaca: `pending` makes execute lose the outcome, `look` is what a later lookup finds.
struct Fake {
    delay_ms: u64,
    pending: bool,
    look: Look,
}

fn fake_fill() -> BrokerFill {
    BrokerFill {
        price: dec!(100),
        broker_order_id: Some("fake-1".into()),
    }
}

#[async_trait]
impl Broker for Fake {
    fn name(&self) -> &'static str {
        "alpaca_paper"
    }
    async fn execute(&self, _req: &OrderRequest<'_>) -> anyhow::Result<BrokerFill> {
        tokio::time::sleep(std::time::Duration::from_millis(self.delay_ms)).await;
        if self.pending {
            return Err(StillPending("connection lost".into()).into());
        }
        Ok(fake_fill())
    }
    async fn lookup(&self, _id: &str) -> anyhow::Result<BrokerLookup> {
        Ok(match self.look {
            Look::Filled => BrokerLookup::Filled(fake_fill()),
            Look::Dead => BrokerLookup::Dead("order not found at broker".into()),
            Look::Pending => BrokerLookup::Pending,
        })
    }
}

async fn alpaca_svc(e: &Env, fake: Fake) -> Arc<Service> {
    sqlx::query(
        "INSERT INTO bots (slug,name,strategy_kind,params,starting_cash,broker)
         VALUES ('alp','A','crossover','{}',100000,'alpaca_paper')",
    )
    .execute(&e.pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO cash SELECT id, 100000 FROM bots WHERE slug='alp'")
        .execute(&e.pool)
        .await
        .unwrap();
    Arc::new(Service {
        pool: e.pool.clone(),
        sim: Arc::new(SimBroker),
        alpaca: Some(Arc::new(fake)),
        force_market_open: true,
    })
}

async fn age_orders(pool: &PgPool, minutes: i32) {
    sqlx::query("UPDATE orders SET submitted_at = now() - make_interval(mins => $1)")
        .bind(minutes)
        .execute(pool)
        .await
        .unwrap();
}

#[tokio::test]
async fn a_lost_broker_outcome_stays_submitted_not_rejected() {
    let e = setup().await;
    let svc = alpaca_svc(
        &e,
        Fake {
            delay_ms: 0,
            pending: true,
            look: Look::Filled,
        },
    )
    .await;
    let s = signal(&e.pool, "alp", "AAPL").await;
    let o = svc
        .place(order(s, "alp", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.status, "submitted");
    assert!(o.reject_reason.is_none());
    assert_eq!(cash(&e.pool, "alp").await, dec!(100000));
}

#[tokio::test]
async fn reconcile_books_a_lost_fill_exactly_once() {
    let e = setup().await;
    let svc = alpaca_svc(
        &e,
        Fake {
            delay_ms: 0,
            pending: true,
            look: Look::Filled,
        },
    )
    .await;
    let s = signal(&e.pool, "alp", "AAPL").await;
    let o = svc
        .place(order(s, "alp", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(
        svc.reconcile_stale().await.unwrap(),
        0,
        "too recent to touch"
    );
    age_orders(&e.pool, 10).await;
    assert_eq!(svc.reconcile_stale().await.unwrap(), 1);
    let done = svc.get_order(o.id).await.unwrap().unwrap();
    assert_eq!(done.status, "filled");
    assert_eq!(done.fill_price, Some(dec!(100)));
    let after = cash(&e.pool, "alp").await;
    assert_eq!(after, dec!(100000) - done.qty * dec!(100));
    assert_eq!(svc.reconcile_stale().await.unwrap(), 0);
    assert_eq!(cash(&e.pool, "alp").await, after, "no double booking");
    let fills: i64 = sqlx::query_scalar("SELECT count(*) FROM fills")
        .fetch_one(&e.pool)
        .await
        .unwrap();
    assert_eq!(fills, 1);
}

#[tokio::test]
async fn reconcile_rejects_an_order_the_broker_never_had() {
    let e = setup().await;
    let svc = alpaca_svc(
        &e,
        Fake {
            delay_ms: 0,
            pending: true,
            look: Look::Dead,
        },
    )
    .await;
    let s = signal(&e.pool, "alp", "AAPL").await;
    let o = svc
        .place(order(s, "alp", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    age_orders(&e.pool, 10).await;
    assert_eq!(svc.reconcile_stale().await.unwrap(), 1);
    let done = svc.get_order(o.id).await.unwrap().unwrap();
    assert_eq!(done.status, "rejected");
    assert!(done.reject_reason.unwrap().contains("not found at broker"));
    assert_eq!(cash(&e.pool, "alp").await, dec!(100000));
}

#[tokio::test]
async fn reconcile_leaves_a_still_open_order_alone() {
    let e = setup().await;
    let svc = alpaca_svc(
        &e,
        Fake {
            delay_ms: 0,
            pending: true,
            look: Look::Pending,
        },
    )
    .await;
    let s = signal(&e.pool, "alp", "AAPL").await;
    let o = svc
        .place(order(s, "alp", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    age_orders(&e.pool, 10).await;
    assert_eq!(svc.reconcile_stale().await.unwrap(), 0);
    assert_eq!(svc.get_order(o.id).await.unwrap().unwrap().status, o.status);
}

#[tokio::test]
async fn an_order_finishes_even_if_the_caller_hangs_up() {
    let e = setup().await;
    let svc = alpaca_svc(
        &e,
        Fake {
            delay_ms: 600,
            pending: false,
            look: Look::Filled,
        },
    )
    .await;
    let s = signal(&e.pool, "alp", "AAPL").await;
    let body = serde_json::json!({
        "signal_id": s, "bot_slug": "alp", "symbol": "AAPL", "side": "BUY",
        "target_pct": "0.10", "idempotency_key": format!("sig-{s}")
    });
    let app = router(AppState {
        svc,
        arena_key: Arc::new("k".into()),
    });
    let req = Request::builder()
        .method("POST")
        .uri("/v1/orders")
        .header("x-arena-key", "k")
        .header("content-type", "application/json")
        .body(Body::from(body.to_string()))
        .unwrap();
    let call = tokio::spawn(async move { app.oneshot(req).await });
    tokio::time::sleep(std::time::Duration::from_millis(150)).await;
    call.abort(); // the strategies worker's timeout: it hangs up mid-order
    tokio::time::sleep(std::time::Duration::from_millis(1200)).await;
    let status: String = sqlx::query_scalar("SELECT status FROM orders")
        .fetch_one(&e.pool)
        .await
        .unwrap();
    assert_eq!(status, "filled");
    assert!(cash(&e.pool, "alp").await < dec!(100000));
}

async fn add_day_trader(pool: &PgPool) {
    sqlx::query(
        "INSERT INTO bots (slug,name,strategy_kind,params,starting_cash,broker)
         VALUES ('orb','O','orb','{\"allow_short\": true}',100000,'sim')",
    )
    .execute(pool)
    .await
    .unwrap();
    sqlx::query("INSERT INTO cash SELECT id, 100000 FROM bots WHERE slug='orb'")
        .execute(pool)
        .await
        .unwrap();
}

async fn position_qty(pool: &PgPool, bot: &str, symbol: &str) -> Option<Decimal> {
    sqlx::query_scalar(
        "SELECT qty FROM positions p JOIN bots b ON b.id=p.bot_id WHERE b.slug=$1 AND p.symbol=$2",
    )
    .bind(bot)
    .bind(symbol)
    .fetch_optional(pool)
    .await
    .unwrap()
}

#[tokio::test]
async fn a_short_opens_a_negative_position_and_cover_closes_it() {
    let e = setup().await;
    add_day_trader(&e.pool).await;
    let s1 = signal(&e.pool, "orb", "AAPL").await;
    let o = e
        .svc
        .place(order(s1, "orb", "AAPL", "SHORT", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.status, "filled");
    assert_eq!(o.side, "SHORT");
    assert_eq!(o.qty, dec!(100)); // whole shares
    assert_eq!(o.fill_price, Some(dec!(99.98))); // sold 2 bps below the price
    assert_eq!(position_qty(&e.pool, "orb", "AAPL").await, Some(dec!(-100)));
    assert_eq!(cash(&e.pool, "orb").await, dec!(109998)); // proceeds credited
                                                          // Equity: cash plus the (negative) position at the market price of 100.
    assert_eq!(
        cash(&e.pool, "orb").await + dec!(-100) * dec!(100),
        dec!(99998)
    );

    // Covering straight away is an exit, so the cooldown does not apply.
    let s2 = signal(&e.pool, "orb", "AAPL").await;
    let c = e
        .svc
        .place(order(s2, "orb", "AAPL", "COVER", Decimal::ZERO))
        .await
        .unwrap();
    assert_eq!(c.status, "filled");
    assert_eq!(c.qty, dec!(100));
    assert_eq!(c.fill_price, Some(dec!(100.02))); // bought back 2 bps above
    assert_eq!(position_qty(&e.pool, "orb", "AAPL").await, None);
    assert_eq!(cash(&e.pool, "orb").await, dec!(99996)); // lost 0.04 a share on slippage
}

#[tokio::test]
async fn only_bots_that_opt_in_may_sell_short() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s, "crossover", "AAPL", "SHORT", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.status, "rejected");
    assert_eq!(o.reject_reason.unwrap(), "this bot may not sell short");
    assert_eq!(cash(&e.pool, "crossover").await, dec!(100000));
}

#[tokio::test]
async fn a_short_blocks_buying_or_selling_the_same_symbol() {
    let e = setup().await;
    add_day_trader(&e.pool).await;
    let s1 = signal(&e.pool, "orb", "AAPL").await;
    e.svc
        .place(order(s1, "orb", "AAPL", "SHORT", dec!(0.10)))
        .await
        .unwrap();
    let s2 = signal(&e.pool, "orb", "AAPL").await;
    let sell = e
        .svc
        .place(order(s2, "orb", "AAPL", "SELL", Decimal::ZERO))
        .await
        .unwrap();
    assert_eq!(sell.reject_reason.unwrap(), "no position to sell");
    let s3 = signal(&e.pool, "orb", "AAPL").await;
    let buy = e
        .svc
        .place(order(s3, "orb", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert!(buy.status == "rejected");
    assert_eq!(position_qty(&e.pool, "orb", "AAPL").await, Some(dec!(-100)));
}

#[tokio::test]
async fn covering_with_no_short_is_refused() {
    let e = setup().await;
    add_day_trader(&e.pool).await;
    let s = signal(&e.pool, "orb", "AAPL").await;
    let o = e
        .svc
        .place(order(s, "orb", "AAPL", "COVER", Decimal::ZERO))
        .await
        .unwrap();
    assert_eq!(o.reject_reason.unwrap(), "no short position to cover");
}

#[tokio::test]
async fn a_bot_can_raise_its_own_position_cap_but_not_past_the_ceiling() {
    let e = setup().await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.20)))
        .await
        .unwrap();
    assert_eq!(
        o.reject_reason.as_deref(),
        Some("target_pct outside (0, 0.10]")
    );

    sqlx::query("UPDATE bots SET params='{\"max_position_pct\":0.2}' WHERE slug='crossover'")
        .execute(&e.pool)
        .await
        .unwrap();
    let s = signal(&e.pool, "crossover", "SPY").await;
    let o = e
        .svc
        .place(order(s, "crossover", "SPY", "BUY", dec!(0.20)))
        .await
        .unwrap();
    assert_eq!(o.status, "filled");
    assert_eq!(o.qty, dec!(199.9600)); // 20,000 / 100.02

    sqlx::query("UPDATE bots SET params='{\"max_position_pct\":0.9}' WHERE slug='crossover'")
        .execute(&e.pool)
        .await
        .unwrap();
    let s = signal(&e.pool, "crossover", "BTC/USD").await;
    let o = e
        .svc
        .place(order(s, "crossover", "BTC/USD", "BUY", dec!(0.30)))
        .await
        .unwrap();
    assert_eq!(
        o.reject_reason.as_deref(),
        Some("target_pct outside (0, 0.20]")
    );
}

async fn snapshot(pool: &PgPool, bot: &str, age: &str, equity: Decimal) {
    sqlx::query(
        "INSERT INTO equity_snapshots (bot_id, ts, equity)
         SELECT id, now() - $2::interval, $3 FROM bots WHERE slug=$1",
    )
    .bind(bot)
    .bind(age)
    .bind(equity)
    .execute(pool)
    .await
    .unwrap();
}

#[tokio::test]
async fn a_bot_down_three_percent_on_the_day_opens_nothing_more() {
    let e = setup().await;
    // Yesterday it was worth 103,500; today it has 100,000. That is 3.4% down on the day.
    snapshot(&e.pool, "crossover", "2 days", dec!(103500)).await;
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.status, "filled"); // a bot that sets no limit has none

    sqlx::query("UPDATE bots SET params='{\"daily_loss_limit\":0.03}' WHERE slug='crossover'")
        .execute(&e.pool)
        .await
        .unwrap();
    let s = signal(&e.pool, "crossover", "BTC/USD").await;
    let o = e
        .svc
        .place(order(s, "crossover", "BTC/USD", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.status, "rejected");
    assert_eq!(
        o.reject_reason.as_deref(),
        Some("daily loss limit: down more than 3% today")
    );

    sqlx::query("UPDATE bots SET params='{\"daily_loss_limit\":0}' WHERE slug='crossover'")
        .execute(&e.pool)
        .await
        .unwrap();
    let s = signal(&e.pool, "crossover", "SPY").await;
    let o = e
        .svc
        .place(order(s, "crossover", "SPY", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(o.status, "filled"); // 0 switches the limit off again
}

#[tokio::test]
async fn a_bot_far_below_its_peak_opens_nothing_more_but_can_still_sell() {
    let e = setup().await;
    sqlx::query("UPDATE bots SET params='{\"max_drawdown\":0.3}' WHERE slug='crossover'")
        .execute(&e.pool)
        .await
        .unwrap();
    let s = signal(&e.pool, "crossover", "AAPL").await;
    e.svc
        .place(order(s, "crossover", "AAPL", "BUY", dec!(0.10)))
        .await
        .unwrap();
    // Its best day was 150,000; at about 100,000 now it is more than 30% below that.
    snapshot(&e.pool, "crossover", "30 days", dec!(150000)).await;
    snapshot(&e.pool, "crossover", "2 days", dec!(100000)).await;
    let s = signal(&e.pool, "crossover", "SPY").await;
    let o = e
        .svc
        .place(order(s, "crossover", "SPY", "BUY", dec!(0.10)))
        .await
        .unwrap();
    assert_eq!(
        o.reject_reason.as_deref(),
        Some("drawdown limit: more than 30% below its peak")
    );
    let s = signal(&e.pool, "crossover", "AAPL").await;
    let o = e
        .svc
        .place(order(s, "crossover", "AAPL", "SELL", dec!(0)))
        .await
        .unwrap();
    assert_eq!(o.status, "filled");
}
