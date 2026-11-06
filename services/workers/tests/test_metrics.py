import math

import pytest

from arena_workers.common import metrics
from arena_workers.common.metrics import Fill


def test_equity_and_return() -> None:
    eq = metrics.equity_of(1000.0, [(2, 50.0), (1, 25.0)])
    assert eq == 1125.0
    assert metrics.return_since_launch(eq, 1000.0) == pytest.approx(0.125)


def test_sharpe_needs_ten_days() -> None:
    assert metrics.sharpe([100 + i for i in range(10)]) is None  # 9 returns


def test_sharpe_value() -> None:
    eq = [100.0]
    for r in [0.01, -0.005] * 6:
        eq.append(eq[-1] * (1 + r))
    rets = [0.01, -0.005] * 6
    mean = sum(rets) / 12
    sd = math.sqrt(sum((r - mean) ** 2 for r in rets) / 11)
    assert metrics.sharpe(eq) == pytest.approx(mean / sd * math.sqrt(252))


def test_sharpe_flat_is_none() -> None:
    assert metrics.sharpe([100.0] * 20) is None


def test_max_drawdown() -> None:
    assert metrics.max_drawdown([100, 120, 90, 110]) == pytest.approx(-0.25)
    assert metrics.max_drawdown([1, 2, 3]) == 0.0
    assert metrics.max_drawdown([]) == 0.0


def test_round_trips_and_win_rate() -> None:
    fills = [Fill("BUY", 10, 100), Fill("SELL", 10, 110), Fill("BUY", 5, 50), Fill("SELL", 5, 40),
             Fill("BUY", 1, 10), Fill("SELL", 1, 12)]
    pnl = metrics.closed_round_trips(fills)
    assert pnl == [100.0, -50.0, 2.0]
    assert metrics.win_rate(pnl) == pytest.approx(2 / 3)
    assert metrics.win_rate(pnl[:2]) is None


def test_today_change() -> None:
    assert metrics.today_change(105, 100) == pytest.approx(0.05)
    assert metrics.today_change(105, None) is None


def test_short_round_trips_gain_when_bought_back_cheaper() -> None:
    wins = metrics.closed_round_trips([Fill("SHORT", 10, 100.0), Fill("COVER", 10, 90.0)])
    assert wins == [100.0]
    loss = metrics.closed_round_trips([Fill("SHORT", 10, 100.0), Fill("COVER", 10, 110.0)])
    assert loss == [-100.0]


def test_long_and_short_trips_mix_and_partial_covers_are_tracked() -> None:
    fills = [Fill("BUY", 5, 10.0), Fill("SELL", 5, 12.0),
             Fill("SHORT", 10, 50.0), Fill("COVER", 4, 45.0), Fill("COVER", 6, 55.0)]
    assert metrics.closed_round_trips(fills) == [10.0, 20.0, -30.0]
    assert metrics.closed_round_trips([Fill("COVER", 5, 10.0)]) == []  # nothing to cover
