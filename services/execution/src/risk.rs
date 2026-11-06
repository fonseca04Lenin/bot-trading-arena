//! Pure risk and sizing rules (spec 6.3). No I/O, so every rule is unit-testable.

use chrono::{DateTime, Datelike, NaiveTime, Utc, Weekday};
use chrono_tz::America::New_York;
use rust_decimal::Decimal;
use rust_decimal_macros::dec;

pub const MAX_POSITIONS: usize = 5;
pub const MAX_BUY_PCT: Decimal = dec!(0.10);
pub const COOLDOWN_MINUTES: i64 = 15;
pub const SLIPPAGE: Decimal = dec!(0.0002);

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Side {
    Buy,
    Sell,
}

impl Side {
    pub fn parse(s: &str) -> Option<Side> {
        match s {
            "BUY" => Some(Side::Buy),
            "SELL" => Some(Side::Sell),
            _ => None,
        }
    }
    pub fn as_str(self) -> &'static str {
        match self {
            Side::Buy => "BUY",
            Side::Sell => "SELL",
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Profile {
    Standard,
    Benchmark,
}

pub struct Inputs {
    pub profile: Profile,
    pub side: Side,
    pub is_crypto: bool,
    pub market_open: bool,
    pub equity: Decimal,
    pub cash: Decimal,
    pub open_positions: usize,
    pub held_qty: Decimal,
    pub target_pct: Decimal,
    pub price: Decimal,
    pub in_cooldown: bool,
    pub already_bought_once: bool,
}

pub fn equity_market_open(now: DateTime<Utc>) -> bool {
    let et = now.with_timezone(&New_York);
    let open = NaiveTime::from_hms_opt(9, 30, 0).unwrap();
    let close = NaiveTime::from_hms_opt(16, 0, 0).unwrap();
    !matches!(et.weekday(), Weekday::Sat | Weekday::Sun) && et.time() >= open && et.time() < close
}

/// Returns the order quantity, or the human-readable reason for rejection.
pub fn size_order(i: &Inputs) -> Result<Decimal, String> {
    if !i.is_crypto && !i.market_open {
        return Err("market closed".into());
    }
    if i.price <= Decimal::ZERO {
        return Err("no price available".into());
    }
    let benchmark = i.profile == Profile::Benchmark;
    // The cooldown stops rapid-fire entries. Exits never wait, so a stop-loss or a quick reversion is not delayed.
    if !benchmark && i.in_cooldown && i.side == Side::Buy {
        return Err(format!(
            "cooldown: one order per symbol per {COOLDOWN_MINUTES} minutes"
        ));
    }
    match i.side {
        Side::Sell => {
            if i.held_qty <= Decimal::ZERO {
                return Err("no position to sell".into());
            }
            if benchmark {
                return Err("benchmark never sells".into());
            }
            Ok(i.held_qty)
        }
        Side::Buy => {
            if i.held_qty > Decimal::ZERO {
                return Err("already holding this symbol".into());
            }
            let notional = if benchmark {
                if i.already_bought_once {
                    return Err("benchmark buys exactly once".into());
                }
                i.cash * i.target_pct.min(Decimal::ONE)
            } else {
                if i.open_positions >= MAX_POSITIONS {
                    return Err(format!("position limit: {MAX_POSITIONS} open positions"));
                }
                if i.target_pct <= Decimal::ZERO || i.target_pct > MAX_BUY_PCT {
                    return Err("target_pct outside (0, 0.10]".into());
                }
                i.equity * i.target_pct
            };
            if notional > i.cash {
                return Err("insufficient cash".into());
            }
            let fill_px = i.price * (Decimal::ONE + SLIPPAGE);
            let qty = (notional / fill_px).round_dp_with_strategy(
                if i.is_crypto { 6 } else { 4 },
                rust_decimal::RoundingStrategy::ToZero,
            );
            if qty <= Decimal::ZERO {
                return Err("order too small".into());
            }
            Ok(qty)
        }
    }
}

/// Simulated fill price: 2 bps against the trader.
pub fn sim_fill_price(side: Side, price: Decimal) -> Decimal {
    match side {
        Side::Buy => price * (Decimal::ONE + SLIPPAGE),
        Side::Sell => price * (Decimal::ONE - SLIPPAGE),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::TimeZone;

    fn base() -> Inputs {
        Inputs {
            profile: Profile::Standard,
            side: Side::Buy,
            is_crypto: false,
            market_open: true,
            equity: dec!(100000),
            cash: dec!(100000),
            open_positions: 0,
            held_qty: Decimal::ZERO,
            target_pct: dec!(0.10),
            price: dec!(100),
            in_cooldown: false,
            already_bought_once: false,
        }
    }

    #[test]
    fn sizes_ten_percent_of_equity_after_slippage() {
        let qty = size_order(&base()).unwrap();
        assert_eq!(qty, dec!(99.9800)); // 10,000 / 100.02 truncated to 4 dp
        assert!(qty * dec!(100.02) <= dec!(10000));
    }

    #[test]
    fn rejects_when_market_closed_but_allows_crypto() {
        let mut i = base();
        i.market_open = false;
        assert_eq!(size_order(&i).unwrap_err(), "market closed");
        i.is_crypto = true;
        assert!(size_order(&i).is_ok());
    }

    #[test]
    fn enforces_position_limit() {
        let mut i = base();
        i.open_positions = 5;
        assert!(size_order(&i).unwrap_err().starts_with("position limit"));
        i.open_positions = 4;
        assert!(size_order(&i).is_ok());
    }

    #[test]
    fn sells_ignore_the_cooldown() {
        let mut i = base();
        i.side = Side::Sell;
        i.held_qty = dec!(5);
        i.in_cooldown = true;
        assert_eq!(size_order(&i).unwrap(), dec!(5));
    }

    #[test]
    fn enforces_cooldown() {
        let mut i = base();
        i.in_cooldown = true;
        assert!(size_order(&i).unwrap_err().starts_with("cooldown"));
    }

    #[test]
    fn rejects_oversized_target_and_zero() {
        let mut i = base();
        i.target_pct = dec!(0.11);
        assert!(size_order(&i).is_err());
        i.target_pct = Decimal::ZERO;
        assert!(size_order(&i).is_err());
    }

    #[test]
    fn rejects_insufficient_cash() {
        let mut i = base();
        i.cash = dec!(5000);
        assert_eq!(size_order(&i).unwrap_err(), "insufficient cash");
    }

    #[test]
    fn sell_closes_full_position_and_needs_one() {
        let mut i = base();
        i.side = Side::Sell;
        assert_eq!(size_order(&i).unwrap_err(), "no position to sell");
        i.held_qty = dec!(12.5);
        assert_eq!(size_order(&i).unwrap(), dec!(12.5));
    }

    #[test]
    fn no_double_buy_of_same_symbol() {
        let mut i = base();
        i.held_qty = dec!(1);
        assert_eq!(size_order(&i).unwrap_err(), "already holding this symbol");
    }

    #[test]
    fn benchmark_exempt_from_sizing_slots_and_cooldown_but_buys_once() {
        let mut i = base();
        i.profile = Profile::Benchmark;
        i.target_pct = Decimal::ONE;
        i.open_positions = 9;
        i.in_cooldown = true;
        let qty = size_order(&i).unwrap();
        let cost = qty * dec!(100.02);
        assert!(cost <= dec!(100000) && cost > dec!(99990));
        i.already_bought_once = true;
        assert_eq!(size_order(&i).unwrap_err(), "benchmark buys exactly once");
        i.already_bought_once = false;
        i.side = Side::Sell;
        i.held_qty = dec!(5);
        assert_eq!(size_order(&i).unwrap_err(), "benchmark never sells");
    }

    #[test]
    fn slippage_is_two_bps_against_trader() {
        assert_eq!(sim_fill_price(Side::Buy, dec!(100)), dec!(100.02));
        assert_eq!(sim_fill_price(Side::Sell, dec!(100)), dec!(99.98));
    }

    #[test]
    fn market_hours_in_eastern_time() {
        // Mon 2026-01-05: 15:00 UTC = 10:00 ET (open), 13:00 UTC = 08:00 ET, 21:00 UTC = 16:00 ET.
        assert!(equity_market_open(
            Utc.with_ymd_and_hms(2026, 1, 5, 15, 0, 0).unwrap()
        ));
        assert!(!equity_market_open(
            Utc.with_ymd_and_hms(2026, 1, 5, 13, 0, 0).unwrap()
        ));
        assert!(!equity_market_open(
            Utc.with_ymd_and_hms(2026, 1, 10, 15, 0, 0).unwrap()
        ));
        assert!(!equity_market_open(
            Utc.with_ymd_and_hms(2026, 1, 5, 21, 0, 0).unwrap()
        ));
    }
}
