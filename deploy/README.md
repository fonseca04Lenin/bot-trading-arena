# Deploying

Deployment needs accounts and DNS that only the owner can grant, so it is a checklist, not a script.

1. **Neon**: create a Postgres 16 database. Run `DATABASE_URL=<neon url> scripts/migrate.sh`.
2. **Railway**: one project, five services from this repo.

   | Service | Dockerfile | Start command |
   |---|---|---|
   | execution | `deploy/Dockerfile.execution` | `arena-execution` |
   | api | `deploy/Dockerfile.python` | `uvicorn arena_api.main:app --host 0.0.0.0 --port $PORT` |
   | ingest | `deploy/Dockerfile.python` | `arena-ingest` |
   | strategies | `deploy/Dockerfile.python` | `arena-strategies` |
   | scorer | `deploy/Dockerfile.python` | `arena-scorer` |

   Environment: `ARENA_ENV=production`, `DATABASE_URL`, a long random `ARENA_KEY` (shared by execution and the workers),
   `EXECUTION_URL`, `MARKET_DATA_SOURCE=alpaca`, `ALPACA_API_KEY` / `ALPACA_API_SECRET` (paper keys),
   `ALPACA_TRADING_BASE_URL=https://paper-api.alpaca.markets`, and `CORS_ORIGINS=https://arena.elvinfonseca.com`.
   In production the execution service refuses a default `ARENA_KEY`, ignores `ARENA_FORCE_MARKET_OPEN`, and ingest refuses synthetic data.
3. **Vercel**: import `apps/web` as the project root. Set `API_URL` and `NEXT_PUBLIC_API_URL` to the Railway API URL.
   Add the `arena` CNAME for `elvinfonseca.com`.
4. Run the Playwright smoke tests against production: `E2E_BASE_URL=https://arena.elvinfonseca.com npx playwright test`.

## Private daily report (optional)

The scorer service emails a PDF trade log plus two CSVs (trades, standings) every weekday at 4:15 PM ET, with the day's
best bot in the subject line. Nothing is served over HTTP; the data leaves only as the email.

1. Create a free account at resend.com and an API key.
2. On the **scorer** service in Railway, set `RESEND_API_KEY` and `REPORT_EMAIL_TO` (your address).
   The default sender (`onboarding@resend.dev`) can only deliver to the email the Resend account was created with.
   To send to another address, verify a domain in Resend and set `REPORT_EMAIL_FROM`.
3. To test, also set `REPORT_SEND_ON_START=1`, redeploy, check your inbox, then remove that variable.

A failed send is logged as `daily report failed` and retried on the next tick; it never stops the scorer.
