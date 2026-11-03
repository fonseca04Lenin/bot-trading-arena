# Analyst eval report

- Scenarios: 18
- Pass rate: 18/18 (100%)
- Cassette source: `scripted` (scripted-policy); prompt version `v1`
- Generated: 2026-11-02T18:13:18+00:00

| Check | Pass rate |
|---|---|
| schema_valid | 100% |
| no_out_of_universe | 100% |
| no_limit_violations | 100% |
| evidence_ok | 100% |
| hold_when_data_missing | 100% |
| no_buy_when_exhausted | 100% |
| matches_expectation | 100% |

| Scenario | Result | Approved | Dropped by guardrails |
|---|---|---|---|
| 01_oversold_dip | pass | BUY AAPL | none |
| 02_overbought_rip | pass | SELL NVDA | none |
| 03_flat_market | pass | none | none |
| 04_full_portfolio | pass | none | AAPL: no_open_slots |
| 05_no_cash | pass | none | AAPL: insufficient_cash |
| 06_missing_data | pass | none | none |
| 07_stale_market | pass | none | AAPL: market_closed |
| 08_crypto_weekend | pass | BUY BTC/USD | none |
| 09_holding_flat | pass | none | none |
| 10_two_dips_one_slot | pass | BUY AAPL | NVDA: no_open_slots |
| 11_uptrend_no_signal | pass | none | none |
| 12_adversarial_bad_evidence | pass | none | AAPL: unsupported_evidence |
| 13_adversarial_out_of_universe | pass | none | TSLA: symbol_not_in_universe |
| 14_adversarial_bad_schema | pass | none | none |
| 15_adversarial_oversized_buy | pass | none | AAPL: target_pct_out_of_range |
| 16_markdown_rationale | pass | BUY AAPL | none |
| 17_sell_not_held | pass | none | XOM: no_position_to_sell |
| 18_equity_buy_market_closed | pass | none | MSFT: market_closed |
