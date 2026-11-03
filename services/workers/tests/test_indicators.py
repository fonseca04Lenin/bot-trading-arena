import pytest

from arena_workers.common.indicators import daily_returns, highest, lowest, rsi, sma


def test_sma_values_and_warmup() -> None:
    assert sma([1, 2, 3, 4, 5], 3) == 4.0
    assert sma([2, 4], 2) == 3.0
    assert sma([1, 2], 3) is None
    assert sma([], 1) is None


def test_rsi_known_values() -> None:
    assert rsi([1, 2, 3, 4, 5, 6], 5) == 100.0
    assert rsi([6, 5, 4, 3, 2, 1], 5) == 0.0
    assert rsi([5.0] * 6, 5) == 50.0
    assert rsi([1, 2, 3], 14) is None


def test_rsi_wilder_smoothing() -> None:
    # Hand-computed: period 2, closes 10,11,10,12. First avg gain=.5 loss=.5; then gain 2:
    # avg_gain=(.5*1+2)/2=1.25, avg_loss=(.5*1+0)/2=.25, RS=5, RSI=100-100/6
    assert rsi([10, 11, 10, 12], 2) == pytest.approx(100 - 100 / 6)


def test_highest_lowest() -> None:
    assert highest([1, 5, 3, 4], 3) == 5
    assert highest([1, 5, 3, 4], 2) == 4
    assert lowest([4, 2, 3, 9], 3) == 2
    assert highest([1], 2) is None and lowest([1], 2) is None


def test_daily_returns() -> None:
    assert daily_returns([100, 110, 99]) == pytest.approx([0.1, -0.1])
    assert daily_returns([100]) == []
    assert daily_returns([0, 5]) == []
