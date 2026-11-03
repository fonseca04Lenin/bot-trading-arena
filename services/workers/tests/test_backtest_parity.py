import random
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest

from arena_workers.common import db
from arena_workers.common.config import load_settings
from arena_workers.common.models import Bar
from arena_workers.strategies.backtest import generate_signals, run_backtest
from arena_workers.strategies.main import process_bar
from arena_workers.strategies.rules import Breakout, Crossover, RubberBand


def walk(n: int = 400, seed: int = 3) -> list[Bar]:
    rng = random.Random(seed)
    px, t, out = 100.0, datetime(2026, 1, 5, 14, 30, tzinfo=UTC), []
    for _ in range(n):
        c = px * (1 + rng.gauss(0, 0.01))
        out.append(Bar(t, px, max(px, c) * 1.002, min(px, c) * 0.998, c, 100))
        px, t = c, t + timedelta(minutes=5)
    return out


@pytest.mark.parametrize("strat", [Crossover(), RubberBand(), Breakout()])
def test_backtest_signals_have_data_and_metrics(strat: Any) -> None:
    res = run_backtest(strat, "AAPL", walk())
    assert len(res.equity) == 400
    assert res.equity[0][1] == pytest.approx(100_000.0)
    assert -1 < res.max_drawdown <= 0


def test_live_path_matches_backtest(conn: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    """Replaying bars bar-by-bar through the live worker emits the same signals as the backtester."""
    db.seed_bots(conn)
    bars = walk()
    expected = generate_signals(Breakout(), "AAPL", bars)
    assert expected, "fixture should trigger signals"

    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        body = json.loads(request.content)
        posted.append(body)
        # Mimic the execution service: apply the fill to positions so the worker tracks holdings.
        bot = conn.execute("SELECT id FROM bots WHERE slug=%s", (body["bot_slug"],)).fetchone()
        assert bot
        if body["side"] == "BUY":
            conn.execute("INSERT INTO positions VALUES (%s,%s,1,1) ON CONFLICT DO NOTHING", (bot["id"], body["symbol"]))
        else:
            conn.execute("DELETE FROM positions WHERE bot_id=%s AND symbol=%s", (bot["id"], body["symbol"]))
        return httpx.Response(200, json={"status": "filled"})

    monkeypatch.setattr("arena_workers.strategies.main.load_settings", load_settings)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    for i in range(1, len(bars) + 1):
        db.upsert_bars(conn, "AAPL", "5Min", [bars[i - 1]])
        process_bar(conn, client, "AAPL")
    live = [(p["side"]) for p in posted if p["bot_slug"] == "breakout"]
    assert live == [s.side for s in expected]
