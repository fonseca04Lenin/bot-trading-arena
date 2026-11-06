from datetime import UTC, datetime, timedelta

from arena_workers.common.models import Bar, Position
from arena_workers.strategies.orb import OpeningRange
from arena_workers.strategies.rules import build_strategy

OPEN = datetime(2026, 1, 5, 14, 30, tzinfo=UTC)  # 09:30 ET (EST is UTC-5 in January)


def bar(i: int, o: float, h: float, l: float, c: float, start: datetime = OPEN) -> Bar:
    return Bar(start + timedelta(minutes=5 * i), o, h, l, c, 1000.0)


UP = bar(0, 100.0, 100.5, 99.8, 100.3)      # closes up
DOWN = bar(0, 100.3, 100.5, 99.8, 100.0)    # closes down


def test_buys_when_the_opening_candle_closes_up() -> None:
    sig = OpeningRange().on_bar("SPY", [UP], None)
    assert sig is not None and sig.side == "BUY" and sig.bot_slug == "orb"
    metrics = {e["metric"]: e["value"] for e in sig.evidence}
    assert metrics["OR_HIGH"] == 100.5 and metrics["OR_LOW"] == 99.8
    assert 0.01 <= sig.target_pct <= 0.10 and "stop at $99.80" in sig.rationale


def test_sells_short_when_the_opening_candle_closes_down() -> None:
    sig = OpeningRange().on_bar("SPY", [DOWN], None)
    assert sig is not None and sig.side == "SHORT" and "stop at $100.50" in sig.rationale


def test_skips_a_doji_a_tiny_range_and_a_huge_range() -> None:
    assert OpeningRange().on_bar("SPY", [bar(0, 100.0, 100.5, 99.8, 100.0)], None) is None
    assert OpeningRange().on_bar("SPY", [bar(0, 100.0, 100.03, 99.99, 100.02)], None) is None
    assert OpeningRange().on_bar("SPY", [bar(0, 100.0, 104.0, 99.0, 103.0)], None) is None


def test_a_wide_stop_gets_a_smaller_position_than_a_tight_one() -> None:
    tight = OpeningRange(risk_pct=0.0005).on_bar("SPY", [bar(0, 100.0, 100.4, 99.9, 100.3)], None)
    wide = OpeningRange(risk_pct=0.0005).on_bar("SPY", [bar(0, 100.0, 101.0, 99.6, 100.9)], None)
    assert tight is not None and wide is not None and wide.target_pct < tight.target_pct <= 0.10


def test_enters_only_on_the_opening_candle() -> None:
    assert OpeningRange().on_bar("SPY", [UP, bar(1, 100.3, 100.9, 100.2, 100.8)], None) is None


def test_long_stops_out_at_the_candle_low() -> None:
    held = Position("SPY", 10, 100.3)
    sig = OpeningRange().on_bar("SPY", [UP, bar(1, 100.3, 100.3, 99.5, 99.7)], held)
    assert sig is not None and sig.side == "SELL" and "stop" in sig.rationale
    assert OpeningRange().on_bar("SPY", [UP, bar(1, 100.3, 100.6, 100.0, 100.4)], held) is None


def test_short_stops_out_at_the_candle_high() -> None:
    held = Position("SPY", -10, 100.0)
    sig = OpeningRange().on_bar("SPY", [DOWN, bar(1, 100.0, 100.8, 100.0, 100.6)], held)
    assert sig is not None and sig.side == "COVER" and "stop" in sig.rationale
    assert OpeningRange().on_bar("SPY", [DOWN, bar(1, 100.0, 100.2, 99.9, 100.1)], held) is None


def _session_to(last_index: int) -> list[Bar]:
    return [UP] + [bar(i, 100.2, 100.3, 100.1, 100.2) for i in range(1, last_index + 1)]


def test_closes_everything_before_the_bell() -> None:
    long_pos, short_pos = Position("SPY", 10, 100.3), Position("SPY", -10, 100.0)
    # The bar at index 74 starts 15:40; 75 starts 15:45; 76 starts 15:50 and closes at 15:55.
    assert OpeningRange().on_bar("SPY", _session_to(75), long_pos) is None
    sell = OpeningRange().on_bar("SPY", _session_to(76), long_pos)
    assert sell is not None and sell.side == "SELL" and "nearly over" in sell.rationale
    cover = OpeningRange().on_bar("SPY", [DOWN] + _session_to(76)[1:], short_pos)
    assert cover is not None and cover.side == "COVER"


def test_a_position_left_over_from_yesterday_is_closed_at_the_open() -> None:
    yesterday = [bar(i, 100.2, 100.3, 100.1, 100.2) for i in range(10)]
    today = bar(0, 101.0, 101.5, 100.8, 101.2, start=OPEN + timedelta(days=1))
    sig = OpeningRange().on_bar("SPY", yesterday + [today], Position("SPY", 10, 100.0))
    assert sig is not None and sig.side == "SELL" and "from yesterday" in sig.rationale


def test_ignores_crypto_and_days_without_an_opening_candle() -> None:
    assert OpeningRange().on_bar("BTC/USD", [UP], None) is None
    late = [bar(6, 100.0, 100.5, 99.8, 100.3)]  # first bar we have starts at 10:00
    assert OpeningRange().on_bar("SPY", late, None) is None
    assert OpeningRange().on_bar("SPY", [], None) is None


def test_build_strategy_knows_the_day_trader() -> None:
    assert isinstance(build_strategy("orb", {"risk_pct": 0.002}), OpeningRange)
