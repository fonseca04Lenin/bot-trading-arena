#!/usr/bin/env bash
# Starts every service locally in sim mode with synthetic market data. `scripts/dev.sh stop` stops them.
set -euo pipefail
cd "$(dirname "$0")/.."
PIDS="$PWD/.dev.pids"
stop() { [ -f $PIDS ] && while read -r p; do kill "$p" 2>/dev/null || true; done < $PIDS; rm -f $PIDS; }
if [ "${1:-}" = stop ]; then stop; exit 0; fi
stop
export DATABASE_URL="${DATABASE_URL:-postgresql://arena@localhost:5433/arena}"
export ARENA_KEY="${ARENA_KEY:-dev-key}" ARENA_FORCE_MARKET_OPEN=1 MARKET_DATA_SOURCE="${MARKET_DATA_SOURCE:-synthetic}"
export EXECUTION_URL="http://localhost:8081" SYNTHETIC_SPEED="${SYNTHETIC_SPEED:-60}"
[ -f .env ] && set -a && . ./.env && set +a
ROOT="$PWD"; mkdir -p .logs
run() { name=$1; shift; "$@" > "$ROOT/.logs/$name.log" 2>&1 & echo $! >> $PIDS; echo "started $name"; }
(cd services/execution && cargo build -q)
run execution services/execution/target/debug/arena-execution
run ingest .venv/bin/arena-ingest
sleep 4
run strategies .venv/bin/arena-strategies
run scorer .venv/bin/arena-scorer
run api .venv/bin/uvicorn arena_api.main:app --port 8000
if [ -d apps/web/node_modules ]; then (cd apps/web && run web npm run dev); fi
echo "stack up: web http://localhost:3000  api http://localhost:8000/docs  (logs in .logs/)"
wait
