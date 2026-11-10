import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import psycopg
import pytest

from arena_workers.common import db
from arena_workers.common.clock import ET
from arena_workers.common.config import load_settings
from arena_workers.common.models import Bar, Position
from arena_workers.strategies import forecast
from arena_workers.strategies.forecast import Outlook, summarise
from arena_workers.strategies.forecast_trader import ForecastTrader
from arena_workers.strategies.main import process_bar
from arena_workers.strategies.rules import Scorecard, build_strategy

UP = Outlook(exp_ret=0.003, p_up=0.875, sd=0.002, horizon=6, paths=16)
DOWN = Outlook(exp_ret=-0.003, p_up=0.125, sd=0.002, horizon=6, paths=16)


class Stub:
    """A forecaster that answers with a fixed Outlook (or None, or raises) and counts how often it is asked."""

    def __init__(self, answer: Outlook | None | Exception) -> None:
        self.answer, self.calls, self.last_len = answer, 0, 0

    def outlook(self, symbol: str, bars: Sequence[Bar]) -> Outlook | None:
        self.calls += 1
        self.last_len = len(bars)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def et(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=ET).astimezone(UTC)


def session(d: date, until: time = time(15, 55), px: float = 100.0) -> list[Bar]:
    """Five-minute candles for one regular session, 09:30 up to and including the `until` candle."""
    out, t = [], datetime.combine(d, time(9, 30))
    while t.time() <= until:
        ts = et(d, t.time())
        out.append(Bar(ts, px, px + 0.1, px - 0.1, px, 1000.0))
        t += timedelta(minutes=5)
    return out


PRIOR = [date(2025, 12, 31), date(2026, 1, 2)]
TODAY = date(2026, 1, 5)


def history(until: time, px: float = 100.0) -> list[Bar]:
    """Two full prior sessions, then today's session up to `until`."""
    return [b for d in PRIOR for b in session(d, px=px)] + session(TODAY, until, px)


def test_buys_when_most_futures_end_higher_by_enough() -> None:
    sig = ForecastTrader(Stub(UP)).on_bar("AAPL", history(time(10, 30)), None)
    assert sig is not None and sig.side == "BUY" and sig.bot_slug == "analyst"
    assert 0.03 <= sig.target_pct <= 0.10
    ev = {e["metric"]: e["value"] for e in sig.evidence}
    assert ev["P_UP"] == 0.88 and ev["EXP_RET_PCT"] == 0.3 and ev["HORIZON_BARS"] == 6
    assert "14 of 16" in sig.rationale and "+0.30%" in sig.rationale and "Kronos" in sig.rationale


def test_needs_both_agreement_and_a_big_enough_move() -> None:
    small_edge = Outlook(0.0005, 0.94, 0.001, 6, 16)
    unsure = Outlook(0.004, 0.62, 0.006, 6, 16)
    assert ForecastTrader(Stub(small_edge)).on_bar("AAPL", history(time(10, 30)), None) is None
    assert ForecastTrader(Stub(unsure)).on_bar("AAPL", history(time(10, 30)), None) is None


def test_position_size_grows_with_the_expected_move_and_is_capped() -> None:
    small = ForecastTrader(Stub(Outlook(0.002, 0.9, 0.002, 6, 16))).on_bar("AAPL", history(time(10, 30)), None)
    big = ForecastTrader(Stub(Outlook(0.02, 0.9, 0.002, 6, 16))).on_bar("AAPL", history(time(10, 30)), None)
    assert small is not None and big is not None
    assert 0.03 <= small.target_pct < big.target_pct == 0.10


def test_shorts_only_when_allowed_and_only_equities() -> None:
    bars = history(time(10, 30))
    assert ForecastTrader(Stub(DOWN)).on_bar("AAPL", bars, None) is None
    sig = ForecastTrader(Stub(DOWN), allow_short=True).on_bar("AAPL", bars, None)
    assert sig is not None and sig.side == "SHORT" and "short" in sig.rationale and "2 of 16" in sig.rationale
    crypto = [Bar(et(TODAY, time(3, 0)) + timedelta(minutes=5 * i), 100, 100.1, 99.9, 100, 1.0) for i in range(120)]
    assert ForecastTrader(Stub(DOWN), allow_short=True).on_bar("BTC/USD", crypto, None) is None


@pytest.mark.parametrize("start,expected", [
    (time(9, 40), False), (time(9, 45), True), (time(15, 20), True), (time(15, 25), False)])
def test_equity_entries_only_inside_the_trading_window(start: time, expected: bool) -> None:
    sig = ForecastTrader(Stub(UP)).on_bar("AAPL", history(start), None)
    assert (sig is not None) is expected


def test_closes_a_long_when_the_forecast_turns_but_not_before() -> None:
    held = Position("AAPL", 100, 100.0)
    bars = history(time(11, 0))
    turned = ForecastTrader(Stub(Outlook(-0.0004, 0.31, 0.002, 6, 16))).on_bar("AAPL", bars, held)
    assert turned is not None and turned.side == "SELL" and "forecast has turned" in turned.rationale
    assert ForecastTrader(Stub(Outlook(0.0008, 0.62, 0.002, 6, 16))).on_bar("AAPL", bars, held) is None
    # One noisy reading is not a turn: the vote slipped below half but the average is still positive, and vice versa.
    assert ForecastTrader(Stub(Outlook(0.0002, 0.44, 0.002, 6, 16))).on_bar("AAPL", bars, held) is None
    assert ForecastTrader(Stub(Outlook(-0.0003, 0.56, 0.002, 6, 16))).on_bar("AAPL", bars, held) is None


def test_closes_a_short_when_the_forecast_turns() -> None:
    held = Position("AAPL", -100, 100.0)
    sig = ForecastTrader(Stub(UP), allow_short=True).on_bar("AAPL", history(time(11, 0)), held)
    assert sig is not None and sig.side == "COVER" and sig.rationale.startswith("Covered AAPL")
    assert ForecastTrader(Stub(DOWN), allow_short=True).on_bar("AAPL", history(time(11, 0)), held) is None
    mixed = Outlook(-0.0001, 0.62, 0.002, 6, 16)  # the vote says up, the average still says down
    assert ForecastTrader(Stub(mixed), allow_short=True).on_bar("AAPL", history(time(11, 0)), held) is None


def test_stop_loss_exits_without_asking_the_model() -> None:
    stub = Stub(UP)
    long_sig = ForecastTrader(stub).on_bar("AAPL", history(time(11, 0), px=99.0), Position("AAPL", 10, 100.0))
    short_sig = ForecastTrader(stub).on_bar("AAPL", history(time(11, 0), px=101.0), Position("AAPL", -10, 100.0))
    assert long_sig is not None and long_sig.side == "SELL" and "forecast was wrong" in long_sig.rationale
    assert short_sig is not None and short_sig.side == "COVER"
    assert stub.calls == 0


def test_flat_by_the_close_and_never_overnight() -> None:
    held = Position("AAPL", 10, 100.0)
    late = ForecastTrader(Stub(UP)).on_bar("AAPL", history(time(15, 50)), held)
    assert late is not None and late.side == "SELL" and "nearly over" in late.rationale
    assert ForecastTrader(Stub(UP)).on_bar("AAPL", history(time(15, 45)), held) is None
    overnight = ForecastTrader(Stub(UP)).on_bar("AAPL", history(time(9, 30)), held)
    assert overnight is not None and overnight.side == "SELL" and "overnight" in overnight.rationale


def test_crypto_has_no_session_rules() -> None:
    bars = [Bar(et(TODAY, time(3, 0)) + timedelta(minutes=5 * i), 100, 100.1, 99.9, 100, 1.0) for i in range(130)]
    assert bars[-1].ts.astimezone(ET).time() > time(13, 0)  # runs into the afternoon, past any equity cut-off
    sig = ForecastTrader(Stub(UP)).on_bar("BTC/USD", bars[:100], None)  # 03:00 start, so this is a morning candle
    assert sig is not None and sig.side == "BUY"
    held = Position("BTC/USD", 1, 100.0)
    assert ForecastTrader(Stub(UP)).on_bar("BTC/USD", bars, held) is None  # no end-of-day flatten for crypto


def test_the_model_only_sees_regular_session_candles() -> None:
    thin = [Bar(et(TODAY, time(4, 0)) + timedelta(minutes=5 * i), 100, 100, 100, 100, 1.0) for i in range(60)]
    stub = Stub(UP)
    assert ForecastTrader(stub).on_bar("AAPL", thin + history(time(9, 45))[-20:], None) is None
    assert stub.calls == 0  # 21 session candles is not enough context

    stub = Stub(UP)
    sig = ForecastTrader(stub).on_bar("AAPL", thin + history(time(10, 30)), None)
    assert sig is not None and stub.last_len == 100  # trimmed to exactly the context window, pre-market excluded


def test_a_failed_or_empty_forecast_means_no_trade() -> None:
    bars = history(time(10, 30))
    assert ForecastTrader(Stub(RuntimeError("out of memory"))).on_bar("AAPL", bars, None) is None
    assert ForecastTrader(Stub(None)).on_bar("AAPL", bars, None) is None
    assert ForecastTrader(Stub(UP)).on_bar("AAPL", [], None) is None


def test_summarise_reports_direction_confidence_and_spread() -> None:
    out = summarise(100.0, [[100.1, 100.4], [100.0, 100.2], [99.9, 99.8], [100.2, 100.6]])
    assert out is not None and out.paths == 4 and out.horizon == 2
    assert out.p_up == 0.75 and out.exp_ret == pytest.approx(0.0025)
    assert out.sd == pytest.approx(0.0034, abs=1e-4)


def test_summarise_refuses_junk() -> None:
    assert summarise(0.0, [[1.0], [1.0]]) is None
    assert summarise(100.0, [[float("nan")], [float("inf")], [-3.0]]) is None
    assert summarise(100.0, [[101.0]]) is None  # one path says nothing about confidence


def test_unknown_model_falls_back_to_the_scorecard(monkeypatch: pytest.MonkeyPatch) -> None:
    assert isinstance(build_strategy("kronos", {}), Scorecard)
    assert isinstance(build_strategy("kronos", {"allow_short": True, "min_prob": 0.8}, Stub(UP)), ForecastTrader)
    monkeypatch.setenv("KRONOS_DISABLED", "1")
    assert forecast.load_forecaster() is None
    monkeypatch.delenv("KRONOS_DISABLED")

    def no_torch(name: str) -> None:
        raise ImportError("No module named 'torch'")

    monkeypatch.setattr(forecast, "importlib", SimpleNamespace(import_module=no_torch))
    assert forecast.load_forecaster() is None


def _analyst_as_forecaster(conn: psycopg.Connection[dict[str, Any]]) -> None:
    db.seed_bots(conn)
    conn.execute("UPDATE bots SET strategy_kind='kronos', params=%s WHERE slug='analyst'",
                 (json.dumps({"allow_short": True}),))


def _run_worker(conn: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch, start: datetime,
                forecaster: Stub | None) -> list[dict[str, Any]]:
    posted: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        posted.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "filled"})

    monkeypatch.setattr("arena_workers.strategies.main.load_settings", load_settings)
    bars = [Bar(start + timedelta(minutes=5 * i), 100, 100.1, 99.9, 100, 1.0) for i in range(130)]
    db.upsert_bars(conn, "BTC/USD", "5Min", bars)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    process_bar(conn, client, "BTC/USD", forecaster)
    return [p for p in posted if p["bot_slug"] == "analyst"]


def test_worker_trades_a_fresh_candle(conn: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    _analyst_as_forecaster(conn)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    start = now - timedelta(minutes=5 * 129)  # the 130th candle opened just now
    orders = _run_worker(conn, monkeypatch, start, Stub(UP))
    assert [o["side"] for o in orders] == ["BUY"]
    sig = conn.execute("SELECT rationale, evidence FROM signals s JOIN bots b ON b.id=s.bot_id WHERE b.slug='analyst'").fetchone()
    assert sig and "Kronos" in sig["rationale"] and {e["metric"] for e in sig["evidence"]} >= {"P_UP", "EXP_RET_PCT"}


def test_worker_ignores_a_stale_candle(conn: psycopg.Connection[dict[str, Any]], monkeypatch: pytest.MonkeyPatch) -> None:
    _analyst_as_forecaster(conn)
    stub = Stub(UP)
    last_candle = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(hours=3)
    assert _run_worker(conn, monkeypatch, last_candle - timedelta(minutes=5 * 129), stub) == []
    assert stub.calls == 0


def test_worker_without_a_model_falls_back_instead_of_crashing(conn: psycopg.Connection[dict[str, Any]],
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    _analyst_as_forecaster(conn)
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    # Flat candles give the scorecard nothing to act on, so the point here is that the call completes.
    assert _run_worker(conn, monkeypatch, now - timedelta(minutes=5 * 129), None) == []


def test_with_crypto_off_it_opens_no_crypto_but_still_manages_one_it_holds() -> None:
    bars = history(time(11, 0))
    off = ForecastTrader(Stub(UP), trade_crypto=False)
    assert off.on_bar("BTC/USD", bars, None) is None
    assert ForecastTrader(Stub(UP)).on_bar("BTC/USD", bars, None) is not None
    stock = off.on_bar("AAPL", bars, None)
    assert stock is not None and stock.side == "BUY"
    held = Position("BTC/USD", 0.1, 100.0)
    out = ForecastTrader(Stub(DOWN), trade_crypto=False).on_bar("BTC/USD", bars, held)
    assert out is not None and out.side == "SELL"
