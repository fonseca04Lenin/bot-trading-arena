//! Broker adapters. `Sim` fills at the latest price with slippage; `AlpacaPaper` routes to Alpaca's paper API.

use std::time::Duration;

use anyhow::{anyhow, bail, Result};
use async_trait::async_trait;
use rust_decimal::Decimal;
use serde_json::json;

use crate::risk::{sim_fill_price, Side};

pub struct OrderRequest<'a> {
    pub symbol: &'a str,
    pub side: Side,
    pub qty: Decimal,
    pub ref_price: Decimal,
    pub is_crypto: bool,
}

pub struct BrokerFill {
    pub price: Decimal,
    pub broker_order_id: Option<String>,
}

#[async_trait]
pub trait Broker: Send + Sync {
    fn name(&self) -> &'static str;
    async fn execute(&self, req: &OrderRequest<'_>) -> Result<BrokerFill>;
}

pub struct SimBroker;

#[async_trait]
impl Broker for SimBroker {
    fn name(&self) -> &'static str {
        "sim"
    }
    async fn execute(&self, req: &OrderRequest<'_>) -> Result<BrokerFill> {
        Ok(BrokerFill {
            price: sim_fill_price(req.side, req.ref_price),
            broker_order_id: None,
        })
    }
}

pub struct AlpacaPaper {
    http: reqwest::Client,
    base_url: String,
    key: String,
    secret: String,
}

impl AlpacaPaper {
    pub fn new(base_url: &str, key: &str, secret: &str) -> Self {
        Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(15))
                .build()
                .unwrap(),
            base_url: base_url.trim_end_matches('/').to_string(),
            key: key.into(),
            secret: secret.into(),
        }
    }
}

#[async_trait]
impl Broker for AlpacaPaper {
    fn name(&self) -> &'static str {
        "alpaca_paper"
    }

    async fn execute(&self, req: &OrderRequest<'_>) -> Result<BrokerFill> {
        let body = json!({
            "symbol": req.symbol,
            "qty": req.qty.to_string(),
            "side": req.side.as_str().to_lowercase(),
            "type": "market",
            "time_in_force": if req.is_crypto { "gtc" } else { "day" },
        });
        let resp = self
            .http
            .post(format!("{}/v2/orders", self.base_url))
            .header("APCA-API-KEY-ID", &self.key)
            .header("APCA-API-SECRET-KEY", &self.secret)
            .json(&body)
            .send()
            .await?;
        if !resp.status().is_success() {
            bail!(
                "alpaca rejected order: {} {}",
                resp.status(),
                resp.text().await.unwrap_or_default()
            );
        }
        let id = resp.json::<serde_json::Value>().await?["id"]
            .as_str()
            .ok_or_else(|| anyhow!("alpaca response missing id"))?
            .to_string();
        for _ in 0..20 {
            tokio::time::sleep(Duration::from_secs(1)).await;
            let o: serde_json::Value = self
                .http
                .get(format!("{}/v2/orders/{id}", self.base_url))
                .header("APCA-API-KEY-ID", &self.key)
                .header("APCA-API-SECRET-KEY", &self.secret)
                .send()
                .await?
                .json()
                .await?;
            match o["status"].as_str() {
                Some("filled") => {
                    let px = o["filled_avg_price"]
                        .as_str()
                        .ok_or_else(|| anyhow!("no fill price"))?;
                    return Ok(BrokerFill {
                        price: px.parse()?,
                        broker_order_id: Some(id),
                    });
                }
                Some("canceled" | "rejected" | "expired") => bail!("alpaca order {}", o["status"]),
                _ => {}
            }
        }
        bail!("alpaca order {id} not filled within 20s")
    }
}
