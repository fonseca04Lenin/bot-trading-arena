#!/usr/bin/env bash
# Applies db/migrations with dbmate when present, else with psql (up sections only, once each).
set -euo pipefail
cd "$(dirname "$0")/.."
URL="${DATABASE_URL:-postgresql://arena@localhost:5433/arena}"
if command -v dbmate >/dev/null; then
  DATABASE_URL="$URL" dbmate --no-dump-schema --migrations-dir db/migrations up
  exit 0
fi
psql "$URL" -q -v ON_ERROR_STOP=1 -c "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY)"
for f in db/migrations/*.sql; do
  v=$(basename "$f" .sql)
  [ "$(psql "$URL" -Atc "SELECT 1 FROM schema_migrations WHERE version='$v'")" = 1 ] && continue
  awk '/-- migrate:up/{u=1;next} /-- migrate:down/{u=0} u' "$f" | psql "$URL" -q -v ON_ERROR_STOP=1 -1 -f -
  psql "$URL" -q -c "INSERT INTO schema_migrations VALUES ('$v')"
  echo "applied $v"
done
