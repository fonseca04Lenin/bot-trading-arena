use std::sync::Arc;

use arena_execution::{
    broker::{AlpacaPaper, Broker, SimBroker},
    config::Config,
    http::{router, AppState},
    service::Service,
};
use sqlx::postgres::PgPoolOptions;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt().json().init();
    let cfg = match Config::from_env() {
        Ok(c) => c,
        Err(e) => {
            tracing::error!("refusing to start: {e}");
            std::process::exit(1);
        }
    };
    let pool = PgPoolOptions::new()
        .max_connections(10)
        .connect(&cfg.database_url)
        .await
        .expect("database");
    let alpaca: Option<Arc<dyn Broker>> = if cfg.alpaca_key.is_empty() {
        tracing::warn!("no Alpaca keys: alpaca_paper bots will use the simulator");
        None
    } else {
        Some(Arc::new(AlpacaPaper::new(
            &cfg.alpaca_base_url,
            &cfg.alpaca_key,
            &cfg.alpaca_secret,
        )))
    };
    let svc = Arc::new(Service {
        pool: pool.clone(),
        sim: Arc::new(SimBroker),
        alpaca,
        force_market_open: cfg.force_market_open,
    });

    let beat = pool.clone();
    tokio::spawn(async move {
        loop {
            let _ = sqlx::query(
                "INSERT INTO heartbeats (service, last_seen) VALUES ('execution', now())
                 ON CONFLICT (service) DO UPDATE SET last_seen = now()",
            )
            .execute(&beat)
            .await;
            let _ = sqlx::query("INSERT INTO heartbeat_log (service, ts) VALUES ('execution', now()) ON CONFLICT DO NOTHING")
                .execute(&beat)
                .await;
            tokio::time::sleep(std::time::Duration::from_secs(30)).await;
        }
    });

    let app = router(AppState {
        svc,
        arena_key: Arc::new(cfg.arena_key.clone()),
    });
    let listener = tokio::net::TcpListener::bind(&cfg.bind)
        .await
        .expect("bind");
    tracing::info!("execution service listening on {}", cfg.bind);
    axum::serve(listener, app).await.expect("serve");
}
