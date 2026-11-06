//! Broker adapters. `Sim` fills at the latest price with slippage; `AlpacaPaper` routes to Alpaca's paper API.

use std::time::Duration;

use anyhow::{anyhow, bail, Result};
use async_trait::async_trait;
use rust_decimal::Decimal;
use serde_json::json;

use crate::risk::{sim_fill_price, Side};

pub struct OrderRequest<'a> {
    /// Our order id. Sent to the broker as its client order id so a lost order can be found again.
    pub client_order_id: &'a str,
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

/// The outcome is not known yet: the order may or may not fill at the broker. The caller must leave the order
/// `submitted` for the reconciler instead of marking it rejected, or the ledger and the broker drift apart.
#[derive(Debug)]
pub struct StillPending(pub String);

impl std::fmt::Display for StillPending {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "outcome unknown: {}", self.0)
    }
}

impl std::error::Error for StillPending {}

/// What the broker says about an order we placed earlier.
pub enum BrokerLookup {
    Filled(BrokerFill),
    /// Canceled, rejected, expired or never received: it will not fill.
    Dead(String),
    Pending,
    /// This broker keeps no state to look up (the simulator).
    Unsupported,
}

#[async_trait]
pub trait Broker: Send + Sync {
    fn name(&self) -> &'static str;
    async fn execute(&self, req: &OrderRequest<'_>) -> Result<BrokerFill>;
    async fn lookup(&self, _client_order_id: &str) -> Result<BrokerLookup> {
        Ok(BrokerLookup::Unsupported)
    }
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
            "side": req.side.broker_side(),
            "type": "market",
            "time_in_force": if req.is_crypto { "gtc" } else { "day" },
            "client_order_id": req.client_order_id,
        });
        // A send error can mean the order arrived anyway, so it is "unknown", not "rejected".
        let resp = match self
            .http
            .post(format!("{}/v2/orders", self.base_url))
            .header("APCA-API-KEY-ID", &self.key)
            .header("APCA-API-SECRET-KEY", &self.secret)
            .json(&body)
            .send()
            .await
        {
            Ok(r) => r,
            Err(e) => return Err(StillPending(format!("order request failed: {e}")).into()),
        };
        if !resp.status().is_success() {
            bail!(
                "alpaca rejected order: {} {}",
                resp.status(),
                resp.text().await.unwrap_or_default()
            );
        }
        let id = match resp.json::<serde_json::Value>().await {
            Ok(v) => v["id"]
                .as_str()
                .ok_or_else(|| anyhow!("alpaca response missing id"))?
                .to_string(),
            Err(e) => return Err(StillPending(format!("unreadable order response: {e}")).into()),
        };
        // From here the order exists at Alpaca. Any failure below leaves the outcome unknown.
        for _ in 0..20 {
            tokio::time::sleep(Duration::from_secs(1)).await;
            let o = match self
                .fetch(&format!("{}/v2/orders/{id}", self.base_url))
                .await
            {
                Ok(o) => o,
                Err(e) => return Err(StillPending(format!("order {id}: {e}")).into()),
            };
            match o["status"].as_str() {
                Some("filled") => return Self::fill_of(&o),
                Some("canceled" | "rejected" | "expired") => bail!("alpaca order {}", o["status"]),
                _ => {}
            }
        }
        Err(StillPending(format!("alpaca order {id} not filled within 20s")).into())
    }

    async fn lookup(&self, client_order_id: &str) -> Result<BrokerLookup> {
        let resp = self
            .http
            .get(format!("{}/v2/orders:by_client_order_id", self.base_url))
            .query(&[("client_order_id", client_order_id)])
            .header("APCA-API-KEY-ID", &self.key)
            .header("APCA-API-SECRET-KEY", &self.secret)
            .send()
            .await?;
        if resp.status() == reqwest::StatusCode::NOT_FOUND {
            return Ok(BrokerLookup::Dead("order not found at broker".into()));
        }
        let o: serde_json::Value = resp.error_for_status()?.json().await?;
        Ok(match o["status"].as_str() {
            Some("filled") => BrokerLookup::Filled(Self::fill_of(&o)?),
            Some(s @ ("canceled" | "rejected" | "expired")) => {
                BrokerLookup::Dead(format!("alpaca order {s}"))
            }
            _ => BrokerLookup::Pending,
        })
    }
}

impl AlpacaPaper {
    async fn fetch(&self, url: &str) -> Result<serde_json::Value> {
        Ok(self
            .http
            .get(url)
            .header("APCA-API-KEY-ID", &self.key)
            .header("APCA-API-SECRET-KEY", &self.secret)
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?)
    }

    fn fill_of(o: &serde_json::Value) -> Result<BrokerFill> {
        let px = o["filled_avg_price"]
            .as_str()
            .ok_or_else(|| anyhow!("no fill price"))?;
        Ok(BrokerFill {
            price: px.parse()?,
            broker_order_id: o["id"].as_str().map(str::to_string),
        })
    }
}
