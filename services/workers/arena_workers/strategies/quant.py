"""The Quant: residual mean reversion against the market, sized by volatility.

This follows the single-factor version of Avellaneda & Lee, "Statistical Arbitrage in the US Equity Markets"
(2010), which is the textbook form of the stat-arb that quant desks run:

1. Regress a stock's returns on the market's (here SPY) to get its beta, then strip the market out.
   What is left is the stock's own move, the residual.
2. Sum the residuals into a path and fit an Ornstein-Uhlenbeck (mean-reverting) model to it via an AR(1) fit.
3. Express today's residual as an s-score: standard deviations away from its own equilibrium.
4. Trade the stretch: buy when the stock is unusually cheap against the market (s <= -1.25), exit once it has
   mostly reverted (s >= -0.50). Those are the paper's thresholds.

Position size is scaled by volatility (the risk-targeting that systematic funds apply): a stock that swings twice
as hard gets half the size, never more than the 10% cap the execution service enforces. With `allow_short` it
trades both legs as the paper does: it also sells short a stock that is unusually rich against the market.

The live bot uses the paper's own thresholds (a 60-candle window, entry at 1.25, exit at 0.5). A replay of 60 days of
five-minute candles found a slower setting (a 120-candle window, entry at 2.0, exit at 0) that traded about a sixth as
often and kept more of its profit after costs, but its parameters were chosen on that same sample, so it was not
adopted. `allow_short` adds the paper's short leg; in the same replay it doubled the trades and earned nothing after
costs.

Pure functions, no I/O, like the other rule bots. Every threshold below is a tunable parameter, not a claim
about what real funds run: their actual models are proprietary.
"""

import math
from collections.abc import Sequence

from ..common.models import Bar, Position, Signal
from ..common.universe import BENCHMARK_SYMBOL

BUY_PCT = 0.10
MIN_PCT = 0.02
BARS_PER_YEAR = 78 * 252  # 5-minute bars in a regular US session, times trading days


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs)


def _align(bars: Sequence[Bar], bench: Sequence[Bar], window: int) -> tuple[list[float], list[float]] | None:
    """Closes of both series on the timestamps they share, newest `window + 1` of them."""
    bench_close = {b.ts: b.c for b in bench}
    pairs = [(b.c, bench_close[b.ts]) for b in bars if b.ts in bench_close]
    pairs = pairs[-(window + 1):]
    if len(pairs) < window + 1 or any(s <= 0 or m <= 0 for s, m in pairs):
        return None
    return [s for s, _ in pairs], [m for _, m in pairs]


def _ou_fit(path: Sequence[float]) -> tuple[float, float, float] | None:
    """AR(1) fit X[k+1] = a + b X[k] + e. Returns (b, mean, equilibrium sd), or None if it does not mean-revert."""
    x, y = path[:-1], path[1:]
    mx, my = _mean(x), _mean(y)
    var_x = sum((v - mx) ** 2 for v in x)
    if var_x <= 0:
        return None
    b = sum((u - mx) * (v - my) for u, v in zip(x, y, strict=True)) / var_x
    if not 0.0 < b < 1.0:
        return None
    a = my - b * mx
    resid = [v - (a + b * u) for u, v in zip(x, y, strict=True)]
    var_e = sum(r * r for r in resid) / (len(resid) - 2) if len(resid) > 2 else 0.0
    if var_e <= 0:
        return None
    return b, a / (1.0 - b), math.sqrt(var_e / (1.0 - b * b))


class StatArb:
    slug = "quant"
    needs_benchmark = True  # the strategy worker passes SPY's bars in alongside the stock's own

    def __init__(self, window: int = 60, entry: float = 1.25, exit_: float = 0.50, max_half_life: float = 30.0,
                 target_vol: float = 0.20, stop_loss: float = 0.03, allow_short: bool = False) -> None:
        self.window, self.entry, self.exit = window, entry, exit_
        self.max_half_life, self.target_vol, self.stop_loss = max_half_life, target_vol, stop_loss
        self.allow_short = allow_short
        self.history_bars = max(120, window + 80)  # spare candles, so gaps against SPY still leave a full window

    def on_bar(
        self, symbol: str, bars: Sequence[Bar], position: Position | None,
        benchmark: Sequence[Bar] | None = None,
    ) -> Signal | None:
        if symbol == BENCHMARK_SYMBOL or "/" in symbol or not benchmark or not bars:
            return None  # SPY is the factor itself; crypto does not trade against an equity index
        px, ts = bars[-1].c, bars[-1].ts
        long = position is not None and position.qty > 0
        if position is not None and long and px < position.avg_cost * (1.0 - self.stop_loss):
            why = (f"Sold {symbol} at ${px:,.2f}: it fell {self.stop_loss:.0%} below the ${position.avg_cost:,.2f} "
                   "entry, so the mean-reversion bet looks broken.")
            return Signal(self.slug, symbol, "SELL", 0.0, why, ts, [])
        if position is not None and not long and px > position.avg_cost * (1.0 + self.stop_loss):
            why = (f"Covered {symbol} at ${px:,.2f}: it rose {self.stop_loss:.0%} above the "
                   f"${position.avg_cost:,.2f} entry, so the mean-reversion bet looks broken.")
            return Signal(self.slug, symbol, "COVER", 0.0, why, ts, [])
        aligned = _align(bars, benchmark, self.window)
        if aligned is None:
            return None
        s_px, m_px = aligned
        r = [math.log(s_px[i] / s_px[i - 1]) for i in range(1, len(s_px))]
        m = [math.log(m_px[i] / m_px[i - 1]) for i in range(1, len(m_px))]
        mm, mr = _mean(m), _mean(r)
        var_m = sum((v - mm) ** 2 for v in m)
        if var_m <= 0:
            return None
        beta = sum((u - mm) * (v - mr) for u, v in zip(m, r, strict=True)) / var_m
        path, total = [], 0.0
        for rv, mv in zip(r, m, strict=True):
            total += rv - beta * mv  # the stock's move with the market's share taken out
            path.append(total)
        fit = _ou_fit(path)
        if fit is None:
            return None
        b, centre, sd = fit
        half_life = math.log(2.0) / -math.log(b)
        if half_life > self.max_half_life:
            return None  # reverts too slowly to be worth trading
        s = (path[-1] - centre) / sd
        ann_vol = math.sqrt(sum((v - mr) ** 2 for v in r) / (len(r) - 1)) * math.sqrt(BARS_PER_YEAR)
        ev: list[dict[str, float | str]] = [
            {"metric": "S_SCORE", "value": round(s, 2)},
            {"metric": "BETA", "value": round(beta, 2)},
            {"metric": "HALF_LIFE_BARS", "value": round(half_life, 1)},
            {"metric": "ANN_VOL", "value": round(ann_vol, 3)},
        ]
        size = min(BUY_PCT, max(MIN_PCT, BUY_PCT * self.target_vol / ann_vol)) if ann_vol > 0 else BUY_PCT
        sized = f"Sized at {size:.1%} of equity because its volatility is {ann_vol:.0%} a year."
        if position is None and s <= -self.entry:
            why = (f"Bought {symbol} at ${px:,.2f}: stripped of the market's move (beta {beta:.2f} to {BENCHMARK_SYMBOL}) "
                   f"it sits {abs(s):.2f} standard deviations below its own norm and should revert within about "
                   f"{half_life:.0f} bars. {sized}")
            return Signal(self.slug, symbol, "BUY", size, why, ts, ev)
        if position is None and self.allow_short and s >= self.entry:
            why = (f"Sold {symbol} short at ${px:,.2f}: stripped of the market's move (beta {beta:.2f} to "
                   f"{BENCHMARK_SYMBOL}) it sits {s:.2f} standard deviations above its own norm and should revert "
                   f"within about {half_life:.0f} bars. {sized}")
            return Signal(self.slug, symbol, "SHORT", size, why, ts, ev)
        if position is not None and long and s >= -self.exit:
            why = (f"Sold {symbol} at ${px:,.2f}: the gap to the market has closed, with the s-score back to "
                   f"{s:.2f} from below -{self.entry:.2f}.")
            return Signal(self.slug, symbol, "SELL", 0.0, why, ts, ev)
        if position is not None and not long and s <= self.exit:
            why = (f"Covered {symbol} at ${px:,.2f}: the gap to the market has closed, with the s-score back to "
                   f"{s:.2f} from above {self.entry:.2f}.")
            return Signal(self.slug, symbol, "COVER", 0.0, why, ts, ev)
        return None
