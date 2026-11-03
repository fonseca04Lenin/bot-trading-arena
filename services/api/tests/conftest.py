import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", "postgresql://arena@localhost:5433/arena_test")
os.environ["EVALS_DIR"] = "/nonexistent"

from arena_workers.common import db as wdb  # noqa: E402

from arena_api.main import app  # noqa: E402


@pytest.fixture
def seeded() -> Iterator[psycopg.Connection]:
    c = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    c.execute("TRUNCATE fills, orders, signals, positions, cash, equity_snapshots, agent_runs, heartbeats, "
              "heartbeat_log, headlines, market_notes, bars, bots RESTART IDENTITY CASCADE")
    from psycopg.rows import dict_row
    c.row_factory = dict_row
    wdb.seed_bots(c)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    for sym in ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "BTC/USD", "ETH/USD"]:
        for i in range(120):
            px = 100 + i * 0.1
            c.execute("INSERT INTO bars VALUES (%s,'5Min',%s,%s,%s,%s,%s,10)",
                      (sym, now - timedelta(minutes=5 * (120 - i)), px, px + 1, px - 1, px))
        for i in range(400):
            px = 100 + i * 0.2
            c.execute("INSERT INTO bars VALUES (%s,'1Day',%s,%s,%s,%s,%s,10)",
                      (sym, now - timedelta(days=400 - i), px, px + 1, px - 1, px))
    for b in c.execute("SELECT id FROM bots").fetchall():
        for i in range(400):
            c.execute("INSERT INTO equity_snapshots VALUES (%s,%s,%s)",
                      (b["id"], now - timedelta(minutes=5 * (400 - i)), 100000 + i * 10))
    yield c
    c.close()


@pytest.fixture
def client(seeded: psycopg.Connection) -> Iterator[TestClient]:
    with TestClient(app) as cl:
        yield cl
