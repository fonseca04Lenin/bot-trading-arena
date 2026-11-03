import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from arena_workers.common.models import Bar

TEST_DB = os.environ.get("TEST_DATABASE_URL", "postgresql://arena@localhost:5433/arena_test")


def make_bars(closes: list[float], start: datetime | None = None, spread: float = 0.5) -> list[Bar]:
    t0 = start or datetime(2026, 1, 5, 14, 30, tzinfo=UTC)
    return [Bar(t0 + timedelta(minutes=5 * i), c, c + spread, c - spread, c, 1000.0)
            for i, c in enumerate(closes)]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection[dict[str, Any]]]:
    c = psycopg.connect(TEST_DB, autocommit=True, row_factory=dict_row)
    c.execute("TRUNCATE fills, orders, signals, positions, cash, equity_snapshots, agent_runs, "
              "heartbeats, heartbeat_log, headlines, market_notes, bars, bots RESTART IDENTITY CASCADE")
    yield c
    c.close()
