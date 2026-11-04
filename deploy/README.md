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
