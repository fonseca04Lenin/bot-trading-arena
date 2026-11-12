# Architecture

## Data flow

1. **Ingest** (`arena_workers.ingest`) backfills 5-minute and daily bars, then streams 1-minute bars from Alpaca's websockets
   (stocks on IEX, crypto) and rolls them into 5-minute bars. Each closed bar is written and announced with
   `NOTIFY bar_closed, '<symbol>|<timestamp>'`. Reconnects use exponential backoff. Without keys it runs a synthetic walk.
2. **Strategy workers** listen for `bar_closed`, load recent bars and the bot's position, call the pure `on_bar` function of each
   rule bot, store the signal and POST it to the execution service. They skip a signal that would only be refused for the cooldown.
3. **The Analyst** is a forecast-driven day trader (`ForecastTrader`) that runs inside the strategy workers and asks Kronos, an
   open-source model trained on candlesticks, for a forecast on every closed bar. The LLM version is parked; see below.
4. **Execution** (Rust) validates, de-duplicates by idempotency key, applies the risk rules, routes to a broker adapter and books the fill.
5. **Scorer** writes an equity snapshot per bot every 5 minutes and sends `NOTIFY equity_tick`.
6. **API** serves REST, computes the leaderboard metrics, and relays `NOTIFY` events to WebSocket clients as `trade_filled`,
   `equity_tick` and `price_tick`. Every service writes a heartbeat row every 30 seconds, which feeds `/api/status` and the uptime figure.
7. **Web** server-renders each page from the API, then hydrates the live parts. The client reconnects with backoff and refetches after reconnecting.

## Timeframes

The Analyst, the Quant, the Breakout and the Day Trader decide on every closed 5-minute bar. The Crossover and the Rubber Band
trade daily candles (`"timeframe": "1Day"` in their params): they decide once a day, on the bar that closes at 15:50 ET, reading daily
candles that `db.load_daily` rebuilds from 5-minute bars (the stored daily bars are only refreshed when ingest restarts). They size each
position by volatility (`risk_per_day`). The reason is a replay: on 60 days of 5-minute bars these rules lost before costs and traded
40 to 180 times their equity; on 20 years of daily bars the same rules had a Sharpe ratio near 1.0 with half the benchmark's drawdown.
The Desk backtester replays daily candles with each bot's live params, so it now tests what the live bot does.

## Execution service

- `POST /v1/orders` needs `X-Arena-Key`. The same `idempotency_key` (or `signal_id`) always returns the original order.
- A per-bot row lock serialises risk checks. Sizing and the rules (10% of equity per buy, or up to 20% if the bot's params set `max_position_pct`; five positions; 5-minute cooldown on entries (exits are exempt); no
  equity orders when the market is closed; long only unless a bot's params allow shorts: whole shares, equities only, at most 50% of equity short) live in `risk.rs` as pure functions.
- Two opt-in circuit breakers stop a bot opening new positions, and never stop it closing one: down 3% on the day (`daily_loss_limit`, measured from the last
  equity snapshot before New York midnight), or 30% below its best-ever equity (`max_drawdown`). A bot has one only if its params set it; the Crossover and the Rubber Band do. The benchmark bot is exempt through
  `risk_profile = "benchmark"` in its params, not by slug.
- Brokers: `sim` fills at the latest price with 2 bp of slippage; `alpaca_paper` submits a market order to Alpaca's paper API and polls for the fill.
  If no Alpaca keys are configured, `alpaca_paper` bots fall back to the simulator and the order records the broker actually used.
- A fill, the position change and the cash change commit in one transaction; any failure rolls all three back.
- `/metrics` reports orders by status and p50/p95 signal-to-submit latency.

## The Analyst's forecaster (Kronos)

The live Analyst makes no LLM calls, so the site needs no Anthropic key. On each closed 5-minute bar the strategy worker gives
[Kronos-small](https://huggingface.co/NeoQuasar/Kronos-small) (MIT, 24.7M parameters, trained on candlesticks from 45 exchanges; paper at
arXiv 2508.02739) the last 100 regular-session candles. Kronos writes the next six candles token by token; the worker samples 16 such
futures and keeps where each one ends (`forecast.py`, `kronos_model.py`). Three numbers come out: the share of futures that end higher
(`P_UP`), their average move (`EXP_RET_PCT`) and their spread (`SD_PCT`). They are stored as the signal's evidence, so they show in the Wire and the daily report.

- **Entries** (`forecast_trader.py`): buy when at least 75% of the futures end higher and the average gain is at least 0.06% (1.5 times the
  round trip's slippage); sell short on the mirror image (equities only). Size is 3% to 10% of equity, growing with the expected move.
- **Exits**: when both the vote and the average have flipped (either alone is too noisy with 16 samples), on a 0.5% stop-loss, or at the
  15:50 candle. Equities take no entries before 09:45 or after 15:20 and are never held overnight. Crypto is long only, with no session rules.
- **Cost**: CPU only, about 1.2 s per forecast and 550 MB of RAM in the strategies worker. Ten symbols take about 12 s per candle. Candles
  older than 12 minutes are skipped.
- **Pinned**: the vendored model code (`arena_workers/vendor/kronos`, see its `NOTICE.md`) and the Hugging Face revisions of the weights are
  fixed in the repo, and the Docker build downloads the weights once.
- **Fallbacks**: if the model cannot load (a build with `WITH_KRONOS=0`, a missing install) the Analyst runs its older `Scorecard` rules and
  the worker logs `forecast model not loaded`. Set `KRONOS_DISABLED=1` to do the same without redeploying code. A single failed forecast
  skips that bar.
- **No claim of edge**: the model was not tuned on this universe, and short backtests of 5-minute forecasts are mostly noise. The arena is the test.

## The parked LLM Analyst

The LLM agent described here is not deployed, but its code and evals are kept and CI still replays them. To bring it back, set the
Analyst's `kind` in `BOT_SEED` to `analyst`, run the `arena-analyst` worker, and restore the site copy that describes it.

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
