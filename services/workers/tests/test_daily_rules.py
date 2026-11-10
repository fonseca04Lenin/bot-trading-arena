"""The trend and dip bots on daily candles: the rules, the volatility sizing, and the once-a-day decision."""

import math
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import httpx
import psycopg
import pytest

from arena_workers.common import db
from arena_workers.common.clock import ET
from arena_workers.common.config import load_settings
from arena_workers.common.indicators import volatility
from arena_workers.common.models import Bar, Position
from arena_workers.strategies import main as worker
from arena_workers.strategies.rules import DAILY, Breakout, Crossover, RubberBand, build_strategy


def days(closes: list[float], spread: float = 0.5) -> list[Bar]:
    t0 = datetime(2025, 1, 2, 5, 0, tzinfo=UTC)
    return [Bar(t0 + timedelta(days=i), c, c + spread, c - spread, c, 1e6) for i, c in enumerate(closes)]


def wobble(n: int, drift: float, swing: float, start: float = 100.0) -> list[float]:
    """A drifting price that alternates up and down by `swing`, so it has a known, steady volatility."""
    out, px = [], start
    for i in range(n):
        px *= 1 + drift + (swing if i % 2 else -swing)
        out.append(px)
    return out


def test_volatility_is_the_spread_of_recent_returns() -> None:
    assert volatility([100.0] * 10, 20) is None  # not enough history
    assert volatility([100.0] * 30, 20) == 0.0
    v = volatility(wobble(40, 0.0, 0.02), 20)
    assert v is not None and v == pytest.approx(0.02, rel=0.1)


def test_daily_crossover_buys_while_the_trend_is_up_not_only_on_the_cross() -> None:
    up = wobble(90, 0.004, 0.01)
    daily = Crossover(timeframe=DAILY, risk_per_day=0.003, max_pct=0.20)
    sig = daily.on_bar("AAPL", days(up), None)
    assert sig is not None and sig.side == "BUY" and "20-day average" in sig.rationale
    assert Crossover().on_bar("AAPL", days(up), None) is None  # the five-minute rule waits for the cross itself
    assert daily.on_bar("AAPL", days(up), Position("AAPL", 10, 100.0)) is None  # already in: hold


def test_daily_crossover_sells_when_the_trend_is_down() -> None:
    down = wobble(60, 0.004, 0.01) + wobble(40, -0.006, 0.01, start=120.0)
    sig = Crossover(timeframe=DAILY).on_bar("AAPL", days(down), Position("AAPL", 10, 100.0))
    assert sig is not None and sig.side == "SELL" and "is below" in sig.rationale
    assert Crossover(timeframe=DAILY).on_bar("AAPL", days(down), None) is None


def test_a_jumpier_symbol_gets_a_smaller_position() -> None:
    calm = Crossover(timeframe=DAILY, risk_per_day=0.003, max_pct=0.20).on_bar("SPY", days(wobble(90, 0.004, 0.005)), None)
    wild = Crossover(timeframe=DAILY, risk_per_day=0.003, max_pct=0.20).on_bar("NVDA", days(wobble(90, 0.004, 0.03)), None)
    assert calm is not None and wild is not None
    assert calm.target_pct == pytest.approx(0.20)  # 0.3% a day over ~0.5% volatility would be 60%: capped
    assert wild.target_pct == pytest.approx(0.003 / 0.03, rel=0.15) and "Sized at" in wild.rationale
    flat_size = Crossover(timeframe=DAILY).on_bar("NVDA", days(wobble(90, 0.004, 0.03)), None)
    assert flat_size is not None and flat_size.target_pct == 0.10  # no risk target: the plain 10%


def test_daily_breakout_buys_a_new_high_and_sizes_by_volatility() -> None:
    closes = wobble(60, 0.0, 0.01) + [112.0]
    sig = Breakout(timeframe=DAILY, risk_per_day=0.003, max_pct=0.20).on_bar("AAPL", days(closes), None)
    assert sig is not None and sig.side == "BUY" and "20-day high" in sig.rationale and sig.target_pct <= 0.20
    out = Breakout(timeframe=DAILY).on_bar("AAPL", days(wobble(60, 0.0, 0.01) + [90.0]), Position("AAPL", 5, 100.0))
    assert out is not None and out.side == "SELL" and "10-day low" in out.rationale


def dip(trend: float) -> list[float]:
    """260 days drifting by `trend`, ending in three sharp down days."""
    base = wobble(257, trend, 0.004)
    return base + [base[-1] * 0.985, base[-1] * 0.97, base[-1] * 0.955]


def test_rubber_band_buys_a_dip_only_in_an_uptrend() -> None:
    band = RubberBand(period=2, buy_below=10, timeframe=DAILY, trend=200, exit_ma=5, risk_per_day=0.004, max_pct=0.20)
    sig = band.on_bar("AAPL", days(dip(0.002)), None)
    assert sig is not None and sig.side == "BUY" and "200-day average" in sig.rationale
    assert {e["metric"] for e in sig.evidence} >= {"RSI2", "SMA200"}
    assert band.on_bar("AAPL", days(dip(-0.002)), None) is None  # same dip, but the stock is in a downtrend
    no_filter = RubberBand(period=2, buy_below=10, timeframe=DAILY, exit_ma=5)
    assert no_filter.on_bar("AAPL", days(dip(-0.002)), None) is not None


def test_rubber_band_sells_on_the_first_close_above_its_short_average() -> None:
    band = RubberBand(period=2, buy_below=10, timeframe=DAILY, trend=200, exit_ma=5)
    held = Position("AAPL", 10, 100.0)
    falling = dip(0.002)
    assert band.on_bar("AAPL", days(falling), held) is None  # still below the 5-day average: wait
    bounced = falling + [falling[-1] * 1.05]
    sig = band.on_bar("AAPL", days(bounced), held)
    assert sig is not None and sig.side == "SELL" and "5-day average" in sig.rationale


def test_seeded_daily_bots_run_on_daily_candles_with_a_20_percent_cap() -> None:
    for slug in ("crossover", "rubber-band"):
        seed = next(b for b in db.BOT_SEED if b["slug"] == slug)
        strat = build_strategy(seed["kind"], seed["params"])
        assert getattr(strat, "timeframe", None) == DAILY and getattr(strat, "max_pct", None) == 0.20
        assert getattr(strat, "risk_per_day", 0) > 0 and getattr(strat, "history_bars", 0) <= 260
        assert seed["params"]["daily_loss_limit"] == 0.03 and seed["params"]["max_drawdown"] == 0.30
    assert getattr(build_strategy("crossover", {}), "timeframe", None) == "5Min"  # the class default is unchanged
    breakout = next(b for b in db.BOT_SEED if b["slug"] == "breakout")
    assert getattr(build_strategy("breakout", breakout["params"]), "timeframe", None) == "5Min"  # not switched yet


def test_merge_daily_prefers_days_rebuilt_from_five_minute_candles() -> None:
    def bar(d: date, c: float) -> Bar:
        return Bar(datetime.combine(d, time(0), ET).astimezone(UTC), c, c, c, c, 1.0)

    stored = [bar(date(2026, 1, d), 1.0) for d in (5, 6, 7, 8)]
    rebuilt = [(date(2026, 1, d), bar(date(2026, 1, d), 2.0)) for d in (7, 8, 9)]
    out = db.merge_daily(stored, rebuilt, 10)
    # The 7th is the first rebuilt day, so it may be partial and is dropped in favour of the stored one.
    assert [(b.ts.astimezone(ET).day, b.c) for b in out] == [(5, 1.0), (6, 1.0), (7, 1.0), (8, 2.0), (9, 2.0)]
    assert len(db.merge_daily(stored, rebuilt, 2)) == 2
    assert db.merge_daily(stored, [], 10) == stored


def five_minute_day(d: date, px: float, until: time = time(15, 55)) -> list[Bar]:
    out, t = [], datetime.combine(d, time(9, 30))
    while t.time() <= until:
        ts = datetime.combine(d, t.time(), ET).astimezone(UTC)
        out.append(Bar(ts, px, px + 1, px - 1, px, 100.0))
        t += timedelta(minutes=5)
    return out


def test_load_daily_joins_stored_days_to_days_built_from_five_minute_candles(
        conn: psycopg.Connection[dict[str, Any]]) -> None:
    today = datetime.now(ET).date()
    d1, d2, d3 = today - timedelta(days=3), today - timedelta(days=2), today - timedelta(days=1)
    old = [Bar(datetime.combine(today - timedelta(days=10 - i), time(0), ET).astimezone(UTC), 50, 51, 49, 50.0 + i, 9.0)
           for i in range(5)]
    db.upsert_bars(conn, "AAPL", "1Day", old)
    for d, px in ((d1, 100.0), (d2, 110.0)):
        db.upsert_bars(conn, "AAPL", "5Min", five_minute_day(d, px))
    db.upsert_bars(conn, "AAPL", "5Min", five_minute_day(d3, 120.0, until=time(15, 45)))
    # A thin pre-market candle must not move the day's open, high or low.
    db.upsert_bars(conn, "AAPL", "5Min", [Bar(datetime.combine(d2, time(7, 0), ET).astimezone(UTC), 1, 999, 1, 1, 1.0)])
    out = db.load_daily(conn, "AAPL", 260)
    assert [b.c for b in out[:5]] == [50.0, 51.0, 52.0, 53.0, 54.0]  # the stored history
    assert [(b.ts.astimezone(ET).date(), b.c, b.h, b.l) for b in out[5:]] == [
        (d2, 110.0, 111.0, 109.0), (d3, 120.0, 121.0, 119.0)]  # d1 is the first rebuilt day, so it is dropped


def test_daily_bots_decide_once_a_day_on_the_1545_candle(
        conn: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    db.seed_bots(conn)
    today = datetime.now(ET).date()
    # 80 stored days in a steady uptrend, so the 20-day average is above the 50-day one.
    closes = wobble(80, 0.004, 0.01)
    db.upsert_bars(conn, "AAPL", "1Day", [
        Bar(datetime.combine(today - timedelta(days=81 - i), time(0), ET).astimezone(UTC), c, c + 1, c - 1, c, 1e6)
        for i, c in enumerate(closes)])
    px = closes[-1] * 1.01
    yesterday = five_minute_day(today - timedelta(days=1), px)
    db.upsert_bars(conn, "AAPL", "5Min", yesterday)
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        import json
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "filled"})

    monkeypatch.setattr(worker, "load_settings", load_settings)
    monkeypatch.setattr(worker, "_stale", lambda bars: False)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    session = five_minute_day(today, px)
    by_time = {b.ts.astimezone(ET).time(): b for b in session}

    db.upsert_bars(conn, "AAPL", "5Min", [b for b in session if b.ts.astimezone(ET).time() <= time(11, 0)])
    worker.process_bar(conn, client, "AAPL")
    assert not [p for p in posted if p["bot_slug"] == "crossover"]  # mid-morning: a daily bot stays quiet

    db.upsert_bars(conn, "AAPL", "5Min", [b for b in session if b.ts.astimezone(ET).time() <= time(15, 45)])
    assert worker.is_daily_decision(by_time[time(15, 45)].ts) and not worker.is_daily_decision(by_time[time(15, 40)].ts)
    worker.process_bar(conn, client, "AAPL")
    buys = [p for p in posted if p["bot_slug"] == "crossover"]
    assert len(buys) == 1 and buys[0]["side"] == "BUY" and 0.02 <= float(buys[0]["target_pct"]) <= 0.20
    assert not math.isnan(float(buys[0]["target_pct"]))
