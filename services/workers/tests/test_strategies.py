from conftest import make_bars

from arena_workers.common.models import Position
from arena_workers.strategies.rules import Breakout, Crossover, Index, RubberBand, build_strategy


def _signals(closes: list[float], held: Position | None) -> list[str]:
    bars = make_bars(closes)
    out = []
    for i in range(1, len(bars) + 1):
        s = Crossover().on_bar("AAPL", bars[:i], held)
        if s:
            out.append(s.side)
    return out


def test_crossover_buys_once_on_actual_cross() -> None:
    closes = [100.0] * 50 + [90.0] * 10 + [200.0] * 5
    assert _signals(closes, None) == ["BUY"]  # cross happens once, not on every bar above


def test_crossover_sells_only_when_holding() -> None:
    closes = [100.0] * 50 + [110.0] * 20 + [50.0] * 30
    assert _signals(closes, Position("AAPL", 5, 100)).count("SELL") == 1
    assert "SELL" not in _signals(closes, None)
    sig = next(s for i in range(1, 101)
               if (s := Crossover().on_bar("AAPL", make_bars(closes)[:i], Position("AAPL", 5, 100))))
    assert sig.side == "SELL" and "crossed below" in sig.rationale and "AAPL" in sig.rationale


def test_crossover_warmup() -> None:
    assert Crossover().on_bar("AAPL", make_bars([100.0] * 30), None) is None


def test_rubber_band() -> None:
    falling = make_bars([float(100 - i) for i in range(20)])
    sig = RubberBand().on_bar("MSFT", falling, None)
    assert sig is not None and sig.side == "BUY" and sig.evidence[0]["metric"] == "RSI14"
    assert RubberBand().on_bar("MSFT", falling, Position("MSFT", 1, 90)) is None
    rising = make_bars([float(100 + i) for i in range(20)])
    out = RubberBand().on_bar("MSFT", rising, Position("MSFT", 1, 90))
    assert out is not None and out.side == "SELL"
    assert RubberBand().on_bar("MSFT", rising[:10], None) is None


def test_breakout() -> None:
    bars = make_bars([100.0] * 25 + [110.0])
    sig = Breakout().on_bar("NVDA", bars, None)
    assert sig is not None and sig.side == "BUY" and "20-bar high" in sig.rationale
    down = make_bars([100.0] * 25 + [90.0])
    out = Breakout().on_bar("NVDA", down, Position("NVDA", 1, 100))
    assert out is not None and out.side == "SELL"
    assert Breakout().on_bar("NVDA", make_bars([100.0] * 25), None) is None


def test_index_buys_spy_once() -> None:
    bars = make_bars([580.0])
    sig = Index().on_bar("SPY", bars, None)
    assert sig is not None and sig.target_pct == 1.0
    assert Index().on_bar("SPY", bars, Position("SPY", 1, 580)) is None
    assert Index().on_bar("AAPL", bars, None) is None


def test_build_strategy() -> None:
    assert isinstance(build_strategy("breakout", {"entry": 5, "exit": 3}), Breakout)
    try:
        build_strategy("nope")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
