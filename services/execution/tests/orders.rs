//! Integration tests against a throwaway Postgres (TEST_DATABASE_URL, default arena_test on :5433).

use std::sync::Arc;

use arena_execution::{
    broker::SimBroker,
    http::{router, AppState},
    service::{FillRequest, NewOrder, Service},
};
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
async fn cooldown_rejects_second_order_and_records_reason() {
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
    assert_eq!(o.status, "rejected");
    assert!(o.reject_reason.unwrap().starts_with("cooldown"));
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
