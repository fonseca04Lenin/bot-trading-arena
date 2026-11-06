# Architecture

## Data flow

1. **Ingest** (`arena_workers.ingest`) backfills 5-minute and daily bars, then streams 1-minute bars from Alpaca's websockets
   (stocks on IEX, crypto) and rolls them into 5-minute bars. Each closed bar is written and announced with
   `NOTIFY bar_closed, '<symbol>|<timestamp>'`. Reconnects use exponential backoff. Without keys it runs a synthetic walk.
2. **Strategy workers** listen for `bar_closed`, load recent bars and the bot's position, call the pure `on_bar` function of each
   rule bot, store the signal and POST it to the execution service. They skip a signal that would only be refused for the cooldown.
3. **The Analyst** is a rule bot (`Scorecard`) that runs inside the strategy workers. The LLM version is parked; see below.
4. **Execution** (Rust) validates, de-duplicates by idempotency key, applies the risk rules, routes to a broker adapter and books the fill.
5. **Scorer** writes an equity snapshot per bot every 5 minutes and sends `NOTIFY equity_tick`.
6. **API** serves REST, computes the leaderboard metrics, and relays `NOTIFY` events to WebSocket clients as `trade_filled`,
   `equity_tick` and `price_tick`. Every service writes a heartbeat row every 30 seconds, which feeds `/api/status` and the uptime figure.
7. **Web** server-renders each page from the API, then hydrates the live parts. The client reconnects with backoff and refetches after reconnecting.

## Execution service

- `POST /v1/orders` needs `X-Arena-Key`. The same `idempotency_key` (or `signal_id`) always returns the original order.
- A per-bot row lock serialises risk checks. Sizing and the rules (10% of equity per buy, five positions, 15-minute cooldown on entries (exits are exempt), no
  equity orders when the market is closed, long only unless a bot's params allow shorts: whole shares, equities only, at most 50% of equity short) live in `risk.rs` as pure functions. The benchmark bot is exempt through
  `risk_profile = "benchmark"` in its params, not by slug.
- Brokers: `sim` fills at the latest price with 2 bp of slippage; `alpaca_paper` submits a market order to Alpaca's paper API and polls for the fill.
  If no Alpaca keys are configured, `alpaca_paper` bots fall back to the simulator and the order records the broker actually used.
- A fill, the position change and the cash change commit in one transaction; any failure rolls all three back.
- `/metrics` reports orders by status and p50/p95 signal-to-submit latency.

## The parked LLM Analyst

The Analyst currently runs the rule-based `Scorecard` strategy, so the site needs no Anthropic key. The LLM agent described here is
not deployed, but its code and evals are kept and CI still replays them. To bring it back, set the Analyst's `kind` in `BOT_SEED` to
`analyst`, run the `arena-analyst` worker, and restore the site copy that describes it.

`run_agent` drives a tool loop over four read-only tools (`get_bars`, `get_portfolio`, `get_indicators`, `get_recent_trades`) and
ends with a `submit_decisions` call. The model only proposes. `guardrails.review` then:

1. validates the schema (a failure turns the run into HOLD);
2. checks the symbol, `target_pct` in [0.05, 0.10], confidence in [0, 1], market state, open slots and cash;
3. checks that every cited number matches a value a tool returned in this run, within rounding;
4. strips markdown and newlines, trims the rationale, and drops text that names symbols outside the universe.

The prompt lives in `analyst/prompt.md` and is versioned. Because Claude Sonnet 5.5 and Claude Opus 5.5 reject forced tool choice,
the loop uses `tool_choice: auto` and the prompt tells the model to finish with `submit_decisions`; a run that never submits becomes HOLD.

## Evals

`evals/analyst/scenarios/*.json` are frozen inputs. `evals/analyst/cassettes/*.json` hold recorded responses and carry a `source` field.
The committed cassettes come from `make eval-seed`, a deterministic scripted policy, and are labelled `scripted`. `make eval-live`
re-records them from the real model (labelled `live`) and overwrites them. The report always states which source it used.

## Database

Plain SQL migrations in `db/migrations`, applied by `scripts/migrate.sh` (dbmate when installed). Money and quantities are `NUMERIC`.
Timestamps are UTC and shown in Eastern time on the site.
