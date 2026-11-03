use anyhow::{bail, Result};

pub const PAPER_URL: &str = "https://paper-api.alpaca.markets";

/// Refuses to run against anything but Alpaca's paper endpoint (spec 7.4). There is no live mode.
pub fn ensure_paper(base_url: &str) -> Result<()> {
    if base_url.trim_end_matches('/') != PAPER_URL {
        bail!("ALPACA_TRADING_BASE_URL must be {PAPER_URL}, got {base_url}");
    }
    Ok(())
}

#[derive(Clone, Debug)]
pub struct Config {
    pub database_url: String,
    pub arena_key: String,
    pub alpaca_key: String,
    pub alpaca_secret: String,
    pub alpaca_base_url: String,
    pub bind: String,
    pub force_market_open: bool,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        let get = |k: &str, d: &str| std::env::var(k).unwrap_or_else(|_| d.to_string());
        let production = get("ARENA_ENV", "development") == "production";
        let cfg = Config {
            database_url: get("DATABASE_URL", "postgresql://arena@localhost:5433/arena"),
            arena_key: get("ARENA_KEY", "change-me"),
            alpaca_key: get("ALPACA_API_KEY", ""),
            alpaca_secret: get("ALPACA_API_SECRET", ""),
            alpaca_base_url: get("ALPACA_TRADING_BASE_URL", PAPER_URL),
            bind: get("EXECUTION_BIND", "0.0.0.0:8081"),
            // Only for offline/synthetic development; never honoured in production.
            force_market_open: !production && get("ARENA_FORCE_MARKET_OPEN", "0") == "1",
        };
        ensure_paper(&cfg.alpaca_base_url)?;
        if production && cfg.arena_key == "change-me" {
            bail!("ARENA_KEY must be set in production");
        }
        Ok(cfg)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn accepts_paper_endpoint() {
        assert!(ensure_paper("https://paper-api.alpaca.markets").is_ok());
        assert!(ensure_paper("https://paper-api.alpaca.markets/").is_ok());
    }

    #[test]
    fn rejects_live_or_other_endpoints() {
        assert!(ensure_paper("https://api.alpaca.markets").is_err());
        assert!(ensure_paper("http://localhost:1234").is_err());
        assert!(ensure_paper("").is_err());
    }
}
