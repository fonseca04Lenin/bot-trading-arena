"""The Analyst as a day trader: act on a model's forecast of the next 30 minutes, long or short, flat by the close.

Each time a five-minute candle closes, the forecaster simulates many possible next 30 minutes (see forecast.py).
The Analyst then acts only when the simulations agree and the expected move is big enough to matter:

- Buy when at least `min_prob` of the paths end higher and the average gain is at least `min_edge`.
- Sell short when at least `min_prob` end lower and the average fall is at least `min_edge` (equities only).

Two reasons for those defaults. With 16 paths, 12 agreeing by pure chance happens about 4% of the time, so
`min_prob` of 75% already filters noise. And `min_edge` of 0.06% is 1.5 times the round trip's trading cost
(the simulator charges 0.02% slippage each way), so a trade has to be expected to pay for itself. On SPY the
model's typical 30-minute move is only 0.04%, so expect this bot to trade volatile names far more than SPY.
- Close when the forecast has turned against the position, on a stop-loss, or near the close. "Turned" means both
  the vote (share of paths ending higher) and the average move have crossed to the other side. With only 16 paths
  either one alone is noisy, and exiting on a single noisy reading would cost a round trip of slippage for nothing.

Day-trading discipline for equities, in code and not left to the model: no entries in the first 15 minutes or
the last 35 minutes of the session, nothing held overnight. Crypto trades around the clock, long only, and has
no session rules. Position size grows with the size of the expected move, between 3% and 10% of equity.

The thresholds are tunable parameters. They are not claims about what works: whether this forecaster has any
edge on five-minute candles is exactly what the arena is there to find out.
"""

import logging
from collections.abc import Sequence
from datetime import datetime, time

from ..common.clock import to_et
from ..common.models import Bar, Position, Side, Signal
from .forecast import CONTEXT_BARS, Forecaster, Outlook
from .orb import EXIT_FROM, SESSION_OPEN

log = logging.getLogger("strategies")

FIRST_ENTRY = time(9, 45)  # first candle to start an entry on: skip the opening scramble
LAST_ENTRY = time(15, 20)  # last candle to start an entry on: leaves the whole 30-minute horizon before the exit
SESSION_CLOSE = time(16, 0)
HISTORY_BARS = 300  # candles the worker loads, so a full regular-session context survives filtering


def _px(x: float) -> str:
    return f"{x:,.2f}"


def _in_session(bar: Bar) -> bool:
    return SESSION_OPEN <= to_et(bar.ts).time() < SESSION_CLOSE


class ForecastTrader:
    slug = "analyst"
    history_bars = HISTORY_BARS

    def __init__(self, forecaster: Forecaster, min_prob: float = 0.75, min_edge: float = 0.0006,
                 stop_loss: float = 0.005, allow_short: bool = False, max_pct: float = 0.10,
                 min_bars: int = CONTEXT_BARS, trade_crypto: bool = True) -> None:
        self.forecaster, self.min_prob, self.min_edge = forecaster, min_prob, min_edge
        self.trade_crypto = trade_crypto  # False: no new crypto positions; one already held is still managed
        self.stop_loss, self.allow_short, self.max_pct, self.min_bars = stop_loss, allow_short, max_pct, min_bars

    def on_bar(self, symbol: str, bars: Sequence[Bar], position: Position | None) -> Signal | None:
        crypto = "/" in symbol
        if not crypto:
            # The 90-day backfill includes thin pre- and post-market candles. The model reads the regular session.
            bars = [b for b in bars if _in_session(b)]
        if not bars:
            return None
        last = bars[-1]
        px, ts = last.c, last.ts
        et = to_et(ts)
        long = position is not None and position.qty > 0

        if position is not None:
            if not crypto:
                first_of_day = sum(to_et(b.ts).date() == et.date() for b in bars) == 1
                if first_of_day:
                    return self._exit(symbol, long, px, ts, "it was still open from yesterday, and the Analyst "
                                      "never holds shares overnight", [])
                if et.time() >= EXIT_FROM:
                    return self._exit(symbol, long, px, ts, "the session is nearly over, so the day trade is closed", [])
            if long:
                stopped = px < position.avg_cost * (1 - self.stop_loss)
            else:
                stopped = px > position.avg_cost * (1 + self.stop_loss)
            if stopped:
                way = "fell" if long else "rose"
                return self._exit(symbol, long, px, ts, f"it {way} {self.stop_loss:.1%} past the "
                                  f"${_px(position.avg_cost)} entry, so the forecast was wrong this time", [])
        elif crypto and not self.trade_crypto:
            return None
        elif not crypto and not FIRST_ENTRY <= et.time() <= LAST_ENTRY:
            return None

        if len(bars) < self.min_bars:
            return None
        look = self._look(symbol, bars)
        if look is None:
            return None
        ev: list[dict[str, float | str]] = [
            {"metric": "P_UP", "value": round(look.p_up, 2)},
            {"metric": "EXP_RET_PCT", "value": round(look.exp_ret * 100, 3)},
            {"metric": "SD_PCT", "value": round(look.sd * 100, 3)},
            {"metric": "HORIZON_BARS", "value": look.horizon},
        ]
        ups = round(look.p_up * look.paths)
        outcome = f"{ups} of {look.paths} end higher, with an average move of {look.exp_ret:+.2%}"
        minutes = look.horizon * 5

        if position is not None:
            if long:
                turned = look.p_up < 0.5 and look.exp_ret < 0
            else:
                turned = look.p_up > 0.5 and look.exp_ret > 0
            if not turned:
                return None
            return self._exit(symbol, long, px, ts, f"the forecast has turned: of {look.paths} new simulations of the "
                              f"next {minutes} minutes, {outcome}", ev)

        if look.p_up >= self.min_prob and look.exp_ret >= self.min_edge:
            why = (f"Bought {symbol} at ${_px(px)}: Kronos, an open-source model trained on candlestick charts, "
                   f"simulated the next {minutes} minutes {look.paths} times, and {outcome}.")
            return Signal(self.slug, symbol, "BUY", self._size(look), why, ts, ev)
        if (self.allow_short and not crypto and look.p_up <= 1 - self.min_prob
                and look.exp_ret <= -self.min_edge):
            why = (f"Sold {symbol} short at ${_px(px)}: Kronos, an open-source model trained on candlestick charts, "
                   f"simulated the next {minutes} minutes {look.paths} times, and {outcome}.")
            return Signal(self.slug, symbol, "SHORT", self._size(look), why, ts, ev)
        return None

    def _look(self, symbol: str, bars: Sequence[Bar]) -> Outlook | None:
        try:
            return self.forecaster.outlook(symbol, bars[-self.min_bars:])
        except Exception as exc:  # one bad forecast must not stop the other bots on this candle
            log.error("forecast failed symbol=%s: %s: %s", symbol, type(exc).__name__, exc)
            return None

    def _size(self, look: Outlook) -> float:
        return min(self.max_pct, max(0.03, self.max_pct * abs(look.exp_ret) / (4 * self.min_edge)))

    def _exit(self, symbol: str, long: bool, px: float, ts: datetime, reason: str,
              ev: list[dict[str, float | str]]) -> Signal:
        side: Side = "SELL" if long else "COVER"
        verb = "Sold" if long else "Covered"
        return Signal(self.slug, symbol, side, 0.0, f"{verb} {symbol} at ${_px(px)}: {reason}.", ts, ev)
