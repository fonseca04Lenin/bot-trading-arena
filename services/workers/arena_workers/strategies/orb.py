"""The Day Trader: the 5-minute Opening Range Breakout, long or short, flat by the close.

The rule follows Zarattini & Aziz, "Can Day Trading Really Be Profitable? Evidence of Sustainable Long-term
Profits from Opening Range Breakout (ORB) Day Trading Strategy on S&P 500 ETF" (SSRN 4416622):

1. Wait for the first five-minute candle of the session (09:30 ET) to close.
2. If it closed up, buy at its close and put a stop at the candle's low. If it closed down, sell short and put
   the stop at its high. A doji (open equals close) is skipped.
3. Hold until the stop is hit or the session is nearly over, then close. Nothing is ever held overnight.

Two additions of my own: skip days when the opening candle is unusually tiny or huge, and size each trade so
a stop-out costs about `risk_pct` of equity (a wide stop means a smaller position), capped at the 10% the
execution service allows. The strategy is rules-only and pure, like the other bots. Day trading rewards luck as
well as skill over a few weeks, so treat early results as noise.
"""

from collections.abc import Sequence
from datetime import time

from ..common.clock import to_et
from ..common.models import Bar, Position, Side, Signal

SESSION_OPEN = time(9, 30)
EXIT_FROM = time(15, 50)  # the bar that closes at 15:55, leaving the market open long enough to fill


def _px(x: float) -> str:
    return f"{x:,.2f}"


class OpeningRange:
    slug = "orb"

    def __init__(self, risk_pct: float = 0.001, min_range: float = 0.0005, max_range: float = 0.015,
                 max_pct: float = 0.10, allow_long: bool = True) -> None:
        self.risk_pct, self.min_range, self.max_range, self.max_pct = risk_pct, min_range, max_range, max_pct
        self.allow_long = allow_long  # False skips the days the opening candle closes up: shorts only

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None
    ) -> Signal | None:
        if "/" in symbol or not bars:
            return None  # equities only: the opening range and the close mean nothing for crypto
        last = bars[-1]
        et = to_et(last.ts)
        today = [b for b in bars if to_et(b.ts).date() == et.date()]
        if not today or to_et(today[0].ts).time() != SESSION_OPEN:
            return None  # we do not have today's opening candle
        first = today[0]
        at_open = last.ts == first.ts  # the opening candle has only just closed
        px, ts = last.c, last.ts
        hi, lo = first.h, first.l
        ev: list[dict[str, float | str]] = [{"metric": "OR_HIGH", "value": round(hi, 2)},
                                            {"metric": "OR_LOW", "value": round(lo, 2)}]

        if position is not None:
            long = position.qty > 0
            exit_side: Side = "SELL" if long else "COVER"
            verb = "Sold" if long else "Covered"
            if at_open:
                why = (f"{verb} {symbol} at ${_px(px)}: the position was still open from yesterday, and this "
                       "strategy never holds overnight.")
            elif et.time() >= EXIT_FROM:
                why = f"{verb} {symbol} at ${_px(px)}: the session is nearly over, so the day trade is closed."
            elif long and px <= lo:
                why = (f"{verb} {symbol} at ${_px(px)}: it fell to the opening candle's low of ${_px(lo)}, "
                       "which is the stop.")
            elif not long and px >= hi:
                why = (f"{verb} {symbol} at ${_px(px)}: it rose to the opening candle's high of ${_px(hi)}, "
                       "which is the stop.")
            else:
                return None
            return Signal(self.slug, symbol, exit_side, 0.0, why, ts, ev)

        if not at_open:
            return None  # one entry a day, on the first candle's close
        span = (hi - lo) / first.o if first.o else 0.0
        if span < self.min_range or span > self.max_range:
            return None
        side: Side
        if first.c > first.o:
            if not self.allow_long:
                return None
            stop_frac = (px - lo) / px
            side, size = "BUY", self._size(stop_frac)
            why = (f"Bought {symbol} at ${_px(px)}: the opening five-minute candle closed up (range ${_px(lo)} to "
                   f"${_px(hi)}), so it rides the upside with a stop at ${_px(lo)}.")
        elif first.c < first.o:
            stop_frac = (hi - px) / px
            side, size = "SHORT", self._size(stop_frac)
            why = (f"Sold {symbol} short at ${_px(px)}: the opening five-minute candle closed down (range ${_px(lo)} "
                   f"to ${_px(hi)}), so it rides the downside with a stop at ${_px(hi)}.")
        else:
            return None
        if size is None:
            return None
        ev.append({"metric": "STOP_PCT", "value": round(stop_frac * 100, 2)})
        return Signal(self.slug, symbol, side, size, why, ts, ev)

    def _size(self, stop_frac: float) -> float | None:
        if stop_frac <= 0:
            return None
        return min(self.max_pct, max(0.01, self.risk_pct / stop_frac))
