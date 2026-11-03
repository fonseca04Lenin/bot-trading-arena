# Resume numbers

**These figures come from a local development run on synthetic prices, not from production.** They show the commands that
produce each number; run `scripts/resume_numbers.sh` against the deployed system after the site has been up for at least
7 days and replace this table. Do not quote the uptime or order figures below on a resume.

Measured 2026-11-02 on the developer machine.

| Figure | Local value | How it was produced |
|---|---|---|
| Orders processed | 14 | `GET /api/status` → `total_orders` (`SELECT count(*) FROM orders`) |
| p95 signal-to-submit latency | about 87 ms | `curl localhost:8081/metrics` (`percentile_cont(0.95)` over `orders.latency_ms`) |
| Uptime (30 days) | about 93%, not representative | `GET /api/status` → `uptime.overall`; the dev stack was stopped and restarted repeatedly |
| Automated tests | 95 | pytest workers 45, API 7; `cargo test` 24; vitest 10; Playwright 9 |
| Eval scenarios | 18 (all pass; cassettes are `scripted`, not live model output) | `ls evals/analyst/scenarios`, `make eval` |

Resume bullet to fill in after launch:

> **Paper Trading Arena** | Python, Rust (Axum), TypeScript/React, PostgreSQL, WebSockets, LLM agents | arena.elvinfonseca.com
> - Built a live, event-driven trading simulation where 5 strategy bots, including an LLM agent with tool calls, guardrails, and evals, trade on live market data and stream results to a public dashboard over WebSockets.
> - Built a Rust (Axum) execution service with idempotent order handling and risk checks; processed **N** orders at **p95 X ms** signal-to-submit latency with **99.x%** uptime.
> - Wrote **95+** automated tests and an **18-scenario** eval suite for the AI agent, run in CI with GitHub Actions.
