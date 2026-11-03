#!/usr/bin/env bash
# Prints the figures used in docs/RESUME_NUMBERS.md from the running system. Run it against production
# by pointing API_URL and DATABASE_URL at the production API and database.
set -euo pipefail
cd "$(dirname "$0")/.."
API_URL="${API_URL:-http://localhost:8000}"
echo "== orders, p95 signal-to-submit, uptime, eval (GET $API_URL/api/status) =="
curl -s "$API_URL/api/status" | python3 -c "
import json, sys
d = json.load(sys.stdin)
print('orders processed:', d['total_orders'])
print('p95 signal-to-submit ms:', d['p95_signal_to_submit_ms'])
print('uptime 30d overall:', d['uptime']['overall'], d['uptime']['per_service'])
e = d['eval'] or {}; print('eval:', e.get('passed'), 'of', e.get('scenarios'), 'pass, source', e.get('source'))"
echo "== test counts =="
py=$( (cd services/workers && ../../.venv/bin/pytest --collect-only -q 2>/dev/null | tail -1) )
api=$( (cd services/api && ../../.venv/bin/pytest --collect-only -q 2>/dev/null | tail -1) )
rs=$( (cd services/execution && cargo test -- --list 2>/dev/null | grep -c ': test') )
web=$( (cd apps/web && npx vitest run 2>&1 | grep -E 'Tests ' | sed 's/^ *//') )
e2e=$( (cd apps/web && npx playwright test --list 2>/dev/null | tail -1) )
echo "workers: $py | api: $api | rust: $rs tests | web: $web | e2e: $e2e"
echo "eval scenarios: $(ls evals/analyst/scenarios | wc -l | tr -d ' ')"
