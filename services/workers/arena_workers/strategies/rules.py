"""The rule bots. Pure: bars and position in, optional signal out.

Crossover, Breakout and Rubber Band can read five-minute candles or daily ones (`timeframe`). The live Crossover and
Rubber Band run on daily candles (the Breakout is still on five-minute ones): a replay of 60 days of five-minute candles showed the five-minute versions lose before costs and
trade 40 to 180 times their equity, while the same rules on 20 years of daily candles roughly matched the market's
return for half its drawdown. On daily candles they also size each position by volatility (`risk_per_day`): a
symbol that moves twice as much a day gets half the money, so every position carries about the same risk.
"""

from collections.abc import Sequence
from typing import Any

from ..common.indicators import highest, lowest, rsi, sma, volatility
from ..common.models import Bar, Position, Signal
from ..common.universe import BENCHMARK_SYMBOL
from .forecast import Forecaster
from .forecast_trader import ForecastTrader
from .orb import OpeningRange
from .quant import StatArb

BUY_PCT = 0.10
MIN_PCT = 0.02
LOOKBACK_BARS = 120  # bars the live worker loads for each decision
DAILY = "1Day"
VOL_DAYS = 20


def _px(x: float) -> str:
    return f"{x:,.2f}"


def _qty_hint(price: float, equity: float = 100_000.0) -> float:
    return equity * BUY_PCT / price


def _unit(timeframe: str) -> str:
    return "day" if timeframe == DAILY else "bar"


def _size(closes: Sequence[float], risk_per_day: float, max_pct: float) -> tuple[float, str]:
    """Share of equity to buy, and the sentence that explains it. With no risk target it is simply `max_pct`."""
    vol = volatility(closes, VOL_DAYS) if risk_per_day > 0 else None
    if vol is None or vol <= 0:
        return max_pct, ""
    pct = min(max_pct, max(MIN_PCT, risk_per_day / vol))
    return pct, f" Sized at {pct:.1%} of equity because it moves about {vol:.1%} a day."


class Crossover:
    slug = "crossover"

    def __init__(self, fast: int = 20, slow: int = 50, timeframe: str = "5Min", risk_per_day: float = 0.0,
                 max_pct: float = BUY_PCT) -> None:
        self.fast, self.slow, self.timeframe = fast, slow, timeframe
        self.risk_per_day, self.max_pct = risk_per_day, max_pct
        self.history_bars = slow + VOL_DAYS + 10 if timeframe == DAILY else LOOKBACK_BARS

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        closes = [b.c for b in bars]
        f1, s1 = sma(closes, self.fast), sma(closes, self.slow)
        f0, s0 = sma(closes[:-1], self.fast), sma(closes[:-1], self.slow)
        if None in (f1, s1, f0, s0):
            return None
        assert f1 is not None and s1 is not None and f0 is not None and s0 is not None
        px, ts, unit = closes[-1], bars[-1].ts, _unit(self.timeframe)
        daily = self.timeframe == DAILY
        ev: list[dict[str, float | str]] = [
            {"metric": f"SMA{self.fast}", "value": round(f1, 2)},
            {"metric": f"SMA{self.slow}", "value": round(s1, 2)},
        ]
        # On daily candles it buys whenever the trend is up and it is flat, so a missed day or a full book does not
        # cost it the whole trend. On five-minute candles that would re-buy constantly, so it waits for the cross.
        if f1 > s1 and (daily or f0 <= s0) and position is None:
            pct, sized = _size(closes, self.risk_per_day, self.max_pct)
            verb = "is above" if daily else "crossed above"
            why = (
                f"Bought {symbol} at ${_px(px)}: the {self.fast}-{unit} average (${_px(f1)}) "
                f"{verb} the {self.slow}-{unit} average (${_px(s1)}).{sized}"
            )
            return Signal(self.slug, symbol, "BUY", pct, why, ts, ev)
        if f1 < s1 and (daily or f0 >= s0) and position is not None:
            verb = "is below" if daily else "crossed below"
            why = (
                f"Sold {symbol} at ${_px(px)}: the {self.fast}-{unit} average (${_px(f1)}) "
                f"{verb} the {self.slow}-{unit} average (${_px(s1)})."
            )
            return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
        return None


class RubberBand:
    """Buys a sharp dip. `trend` (an average length, 0 for off) only lets it buy dips in a stock that is still above
    its long-run average, which is what keeps it out of a falling knife. `exit_ma` (0 for off) sells on the first
    close back above a short average; without it the exit is RSI rising above `sell_above`."""

    slug = "rubber-band"

    def __init__(self, period: int = 14, buy_below: float = 30.0, sell_above: float = 70.0,
                 timeframe: str = "5Min", trend: int = 0, exit_ma: int = 0, risk_per_day: float = 0.0,
                 max_pct: float = BUY_PCT) -> None:
        self.period, self.buy_below, self.sell_above = period, buy_below, sell_above
        self.timeframe, self.trend, self.exit_ma = timeframe, trend, exit_ma
        self.risk_per_day, self.max_pct = risk_per_day, max_pct
        self.history_bars = max(trend + 10, LOOKBACK_BARS) if timeframe == DAILY else LOOKBACK_BARS

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        closes = [b.c for b in bars]
        # RSI depends on how much history it sees, so it always reads the same number of candles.
        r = rsi(closes[-LOOKBACK_BARS:], self.period)
        if r is None:
            return None
        px, ts, unit = closes[-1], bars[-1].ts, _unit(self.timeframe)
        ev: list[dict[str, float | str]] = [{"metric": f"RSI{self.period}", "value": round(r, 1)}]
        if position is not None:
            if self.exit_ma:
                avg = sma(closes, self.exit_ma)
                if avg is None or px <= avg:
                    return None
                why = (f"Sold {symbol} at ${_px(px)}: it closed back above its {self.exit_ma}-{unit} average "
                       f"(${_px(avg)}), so the bounce has happened.")
                return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
            if r > self.sell_above:
                why = (
                    f"Sold {symbol} at ${_px(px)}: the {self.period}-{unit} RSI rose to {r:.1f}, "
                    f"above {self.sell_above:.0f}, so the bounce has run its course."
                )
                return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
            return None
        if r >= self.buy_below:
            return None
        still_up = ""
        if self.trend:
            base = sma(closes, self.trend)
            if base is None or px <= base:
                return None  # a dip in a falling stock is not a dip, it is the trend
            ev.append({"metric": f"SMA{self.trend}", "value": round(base, 2)})
            still_up = f" while the price is still above its {self.trend}-{unit} average (${_px(base)})"
        pct, sized = _size(closes, self.risk_per_day, self.max_pct)
        why = (
            f"Bought {symbol} at ${_px(px)}: the {self.period}-{unit} RSI fell to {r:.1f}, "
            f"below {self.buy_below:.0f}{still_up}, so the drop looks overdone.{sized}"
        )
        return Signal(self.slug, symbol, "BUY", pct, why, ts, ev)


class Breakout:
    slug = "breakout"

    def __init__(self, entry: int = 20, exit_: int = 10, timeframe: str = "5Min", risk_per_day: float = 0.0,
                 max_pct: float = BUY_PCT) -> None:
        self.entry, self.exit, self.timeframe = entry, exit_, timeframe
        self.risk_per_day, self.max_pct = risk_per_day, max_pct
        self.history_bars = max(entry, exit_) + VOL_DAYS + 10 if timeframe == DAILY else LOOKBACK_BARS

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        if len(bars) < max(self.entry, self.exit) + 1:
            return None
        prior = bars[:-1]
        px, ts, unit = bars[-1].c, bars[-1].ts, _unit(self.timeframe)
        hi = highest([b.h for b in prior], self.entry)
        lo = lowest([b.l for b in prior], self.exit)
        assert hi is not None and lo is not None
        if px > hi and position is None:
            pct, sized = _size([b.c for b in bars], self.risk_per_day, self.max_pct)
            why = (
                f"Bought {symbol} at ${_px(px)} after it cleared a {self.entry}-{unit} high "
                f"of ${_px(hi)}.{sized}"
            )
            ev: list[dict[str, float | str]] = [{"metric": f"HIGH{self.entry}", "value": round(hi, 2)}]
            return Signal(self.slug, symbol, "BUY", pct, why, ts, ev)
        if px < lo and position is not None:
            why = (
                f"Sold {symbol} at ${_px(px)} after it fell below a {self.exit}-{unit} low "
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


class Scorecard:
    """The Analyst's rule set: buys when trend, price and momentum all agree, sells when at most one still does."""

    slug = "analyst"

    def __init__(self, fast: int = 20, slow: int = 50, period: int = 14, overbought: float = 70.0) -> None:
        self.fast, self.slow, self.period, self.overbought = fast, slow, period, overbought

    def _score(self, closes: Sequence[float]) -> tuple[int, float, float, float] | None:
        f, s, r = sma(closes, self.fast), sma(closes, self.slow), rsi(closes, self.period)
        if f is None or s is None or r is None:
            return None
        return sum((f > s, closes[-1] > f, 50.0 <= r < self.overbought)), f, s, r

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        # RSI depends on how much history it sees, so cap it to what the live worker loads.
        closes = [b.c for b in bars[-LOOKBACK_BARS:]]
        now, prev = self._score(closes), self._score(closes[:-1])
        if now is None or prev is None:
            return None
        score, f, s, r = now
        px, ts = closes[-1], bars[-1].ts
        ev: list[dict[str, float | str]] = [
            {"metric": "SCORE", "value": score},
            {"metric": f"SMA{self.fast}", "value": round(f, 2)},
            {"metric": f"SMA{self.slow}", "value": round(s, 2)},
            {"metric": f"RSI{self.period}", "value": round(r, 1)},
        ]
        if score == 3 and prev[0] < 3 and position is None:
            why = (
                f"Bought {symbol} at ${_px(px)}: all three checks passed. The {self.fast}-bar average (${_px(f)}) "
                f"is above the {self.slow}-bar average (${_px(s)}), price is above both, and RSI is {r:.1f}."
            )
            return Signal(self.slug, symbol, "BUY", BUY_PCT, why, ts, ev)
        if score <= 1 and position is not None:
            why = (
                f"Sold {symbol} at ${_px(px)}: only {score} of 3 checks still passed, with the {self.fast}-bar "
                f"average at ${_px(f)}, the {self.slow}-bar average at ${_px(s)} and RSI at {r:.1f}."
            )
            return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
        return None


def build_strategy(
    kind: str, params: dict[str, Any] | None = None, forecaster: Forecaster | None = None
) -> Crossover | RubberBand | Breakout | Index | Scorecard | StatArb | OpeningRange | ForecastTrader:
    p: dict[str, Any] = params or {}
    timeframe = str(p.get("timeframe", "5Min"))
    risk, cap = float(p.get("risk_per_day", 0.0)), float(p.get("max_position_pct", BUY_PCT))
    if kind == "kronos":
        if forecaster is None:
            return Scorecard()  # no model loaded (see forecast.load_forecaster): keep the Analyst trading on rules
        return ForecastTrader(forecaster, p.get("min_prob", 0.75), p.get("min_edge", 0.0006),
                              p.get("stop_loss", 0.005), bool(p.get("allow_short", False)),
                              trade_crypto=bool(p.get("trade_crypto", True)))
    if kind == "crossover":
        return Crossover(int(p.get("fast", 20)), int(p.get("slow", 50)), timeframe, risk, cap)
    if kind == "rubber-band":
        return RubberBand(int(p.get("period", 14)), p.get("buy_below", 30.0), p.get("sell_above", 70.0),
                          timeframe, int(p.get("trend", 0)), int(p.get("exit_ma", 0)), risk, cap)
    if kind == "breakout":
        return Breakout(int(p.get("entry", 20)), int(p.get("exit", 10)), timeframe, risk, cap)
    if kind == "index":
        return Index()
    if kind == "scorecard":
        return Scorecard(int(p.get("fast", 20)), int(p.get("slow", 50)), int(p.get("period", 14)),
                         p.get("overbought", 70.0))
    if kind == "stat-arb":
        return StatArb(int(p.get("window", 60)), p.get("entry", 1.25), p.get("exit", 0.50),
                       p.get("max_half_life", 30.0), p.get("target_vol", 0.20), p.get("stop_loss", 0.03),
                       bool(p.get("allow_short", False)))
    if kind == "orb":
        return OpeningRange(p.get("risk_pct", 0.001), p.get("min_range", 0.0005), p.get("max_range", 0.015),
                            allow_long=bool(p.get("allow_long", True)))
    raise ValueError(f"unknown strategy kind: {kind}")
