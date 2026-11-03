SHELL := /bin/bash
PY := .venv/bin
PG_BIN := $(shell ls -d /opt/homebrew/opt/postgresql@17/bin 2>/dev/null)
export PATH := $(PG_BIN):$(PATH)
export LC_ALL := en_US.UTF-8
DATABASE_URL ?= postgresql://arena@localhost:5433/arena
TEST_DATABASE_URL ?= postgresql://arena@localhost:5433/arena_test
export DATABASE_URL TEST_DATABASE_URL

.PHONY: setup db migrate dev stop test lint eval eval-seed eval-live types

setup:
	python3.12 -m venv .venv
	$(PY)/pip install -q -e "services/workers[dev]" -e "services/api[dev]"
	cd apps/web && npm install

# Postgres: docker compose when available, else a local cluster in .pgdata (port 5433).
db:
	@if command -v docker >/dev/null; then docker compose up -d postgres; sleep 3; \
	else [ -d .pgdata ] || initdb -D .pgdata -U arena --auth=trust -E UTF8 >/dev/null; \
	  pg_isready -h localhost -p 5433 >/dev/null || pg_ctl -D .pgdata -o "-p 5433 -k /tmp" -l .pgdata/log start >/dev/null; sleep 2; fi
	@createdb -h localhost -p 5433 -U arena arena 2>/dev/null || true
	@createdb -h localhost -p 5433 -U arena arena_test 2>/dev/null || true

migrate: db
	DATABASE_URL=$(DATABASE_URL) scripts/migrate.sh
	DATABASE_URL=$(TEST_DATABASE_URL) scripts/migrate.sh

dev: migrate
	@scripts/dev.sh

stop:
	@scripts/dev.sh stop

test: migrate
	cd services/workers && ../../$(PY)/pytest -q
	cd services/api && ../../$(PY)/pytest -q
	cd services/execution && cargo test --quiet
	cd apps/web && npm test --silent

lint:
	cd services/workers && ../../$(PY)/ruff check . && ../../$(PY)/mypy arena_workers
	cd services/api && ../../$(PY)/ruff check . && ../../$(PY)/mypy arena_api
	cd services/execution && cargo fmt --check && cargo clippy --all-targets -- -D warnings
	cd apps/web && npm run lint && npx tsc --noEmit

eval:
	PYTHONPATH=evals/analyst $(PY)/python evals/analyst/run.py --report

eval-seed:
	PYTHONPATH=evals/analyst $(PY)/python evals/analyst/run.py --mode seed --report

eval-live:
	PYTHONPATH=evals/analyst $(PY)/python evals/analyst/run.py --mode live --report

types:
	$(PY)/python scripts/export_openapi.py > apps/web/openapi.json
	cd apps/web && npx openapi-typescript openapi.json -o src/lib/api-types.ts
