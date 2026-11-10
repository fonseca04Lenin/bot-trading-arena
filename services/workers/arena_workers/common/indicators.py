"""Pure indicator functions. Each returns None until its warm-up period is met."""

import math
from collections.abc import Sequence


def sma(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return sum(values[-period:]) / period


def rsi(closes: Sequence[float], period: int = 14) -> float | None:
    """Wilder's RSI. Needs `period + 1` closes."""
    if len(closes) < period + 1:
        return None
    deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, l in zip(gains[period:], losses[period:], strict=True):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def highest(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return max(values[-period:])


def lowest(values: Sequence[float], period: int) -> float | None:
    if period <= 0 or len(values) < period:
        return None
    return min(values[-period:])


def volatility(closes: Sequence[float], period: int = 20) -> float | None:
    """Standard deviation of the last `period` close-to-close returns: how far one candle typically moves."""
    if period < 2 or len(closes) < period + 1:
        return None
    window = closes[-(period + 1):]
    if any(c <= 0 for c in window):
        return None
    rets = [window[i] / window[i - 1] - 1.0 for i in range(1, len(window))]
    mean = sum(rets) / period
    return math.sqrt(sum((r - mean) ** 2 for r in rets) / (period - 1))


def daily_returns(equities: Sequence[float]) -> list[float]:
    return [
        equities[i] / equities[i - 1] - 1.0
        for i in range(1, len(equities))
        if equities[i - 1] != 0
    ]
