"""The four rule bots. Pure: bars and position in, optional signal out."""

from collections.abc import Sequence

from ..common.indicators import highest, lowest, rsi, sma
from ..common.models import Bar, Position, Signal
from ..common.universe import BENCHMARK_SYMBOL

BUY_PCT = 0.10


def _px(x: float) -> str:
    return f"{x:,.2f}"


def _qty_hint(price: float, equity: float = 100_000.0) -> float:
    return equity * BUY_PCT / price


class Crossover:
    slug = "crossover"

    def __init__(self, fast: int = 20, slow: int = 50) -> None:
        self.fast, self.slow = fast, slow

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        closes = [b.c for b in bars]
        f1, s1 = sma(closes, self.fast), sma(closes, self.slow)
        f0, s0 = sma(closes[:-1], self.fast), sma(closes[:-1], self.slow)
        if None in (f1, s1, f0, s0):
            return None
        assert f1 is not None and s1 is not None and f0 is not None and s0 is not None
        px, ts = closes[-1], bars[-1].ts
        ev: list[dict[str, float | str]] = [
            {"metric": f"SMA{self.fast}", "value": round(f1, 2)},
            {"metric": f"SMA{self.slow}", "value": round(s1, 2)},
        ]
        if f0 <= s0 and f1 > s1 and position is None:
            why = (
                f"Bought {symbol} at ${_px(px)}: the {self.fast}-bar average (${_px(f1)}) "
                f"crossed above the {self.slow}-bar average (${_px(s1)})."
            )
            return Signal(self.slug, symbol, "BUY", BUY_PCT, why, ts, ev)
        if f0 >= s0 and f1 < s1 and position is not None:
            why = (
                f"Sold {symbol} at ${_px(px)}: the {self.fast}-bar average (${_px(f1)}) "
                f"crossed below the {self.slow}-bar average (${_px(s1)})."
            )
            return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
        return None


class RubberBand:
    slug = "rubber-band"

    def __init__(self, period: int = 14, buy_below: float = 30.0, sell_above: float = 70.0) -> None:
        self.period, self.buy_below, self.sell_above = period, buy_below, sell_above

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        closes = [b.c for b in bars]
        r = rsi(closes, self.period)
        if r is None:
            return None
        px, ts = closes[-1], bars[-1].ts
        ev: list[dict[str, float | str]] = [{"metric": f"RSI{self.period}", "value": round(r, 1)}]
        if r < self.buy_below and position is None:
            why = (
                f"Bought {symbol} at ${_px(px)}: the {self.period}-bar RSI fell to {r:.1f}, "
                f"below {self.buy_below:.0f}, so the drop looks overdone."
            )
            return Signal(self.slug, symbol, "BUY", BUY_PCT, why, ts, ev)
        if r > self.sell_above and position is not None:
            why = (
                f"Sold {symbol} at ${_px(px)}: the {self.period}-bar RSI rose to {r:.1f}, "
                f"above {self.sell_above:.0f}, so the bounce has run its course."
            )
            return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
        return None


class Breakout:
    slug = "breakout"

    def __init__(self, entry: int = 20, exit_: int = 10) -> None:
        self.entry, self.exit = entry, exit_

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        if len(bars) < max(self.entry, self.exit) + 1:
            return None
        prior = bars[:-1]
        px, ts = bars[-1].c, bars[-1].ts
        hi = highest([b.h for b in prior], self.entry)
        lo = lowest([b.l for b in prior], self.exit)
        assert hi is not None and lo is not None
        if px > hi and position is None:
            why = (
                f"Bought {symbol} at ${_px(px)} after it cleared a {self.entry}-bar high "
                f"of ${_px(hi)}."
            )
            ev: list[dict[str, float | str]] = [{"metric": f"HIGH{self.entry}", "value": round(hi, 2)}]
            return Signal(self.slug, symbol, "BUY", BUY_PCT, why, ts, ev)
        if px < lo and position is not None:
            why = (
                f"Sold {symbol} at ${_px(px)} after it fell below a {self.exit}-bar low "
                f"of ${_px(lo)}."
            )
            ev = [{"metric": f"LOW{self.exit}", "value": round(lo, 2)}]
            return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
        return None


class Index:
    slug = "index"

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        if symbol != BENCHMARK_SYMBOL or position is not None or not bars:
            return None
        px = bars[-1].c
        why = f"Bought {symbol} at ${_px(px)} with all of its cash and will hold it, as the benchmark."
        return Signal(self.slug, symbol, "BUY", 1.0, why, bars[-1].ts, [])


def build_strategy(kind: str, params: dict[str, float] | None = None) -> Crossover | RubberBand | Breakout | Index:
    p = params or {}
    if kind == "crossover":
        return Crossover(int(p.get("fast", 20)), int(p.get("slow", 50)))
    if kind == "rubber-band":
        return RubberBand(int(p.get("period", 14)), p.get("buy_below", 30.0), p.get("sell_above", 70.0))
    if kind == "breakout":
        return Breakout(int(p.get("entry", 20)), int(p.get("exit", 10)))
    if kind == "index":
        return Index()
    raise ValueError(f"unknown strategy kind: {kind}")
