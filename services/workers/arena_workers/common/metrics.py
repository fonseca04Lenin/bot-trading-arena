"""Scoring formulas (spec §6.4). Pure functions."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .indicators import daily_returns

MIN_SHARPE_DAYS = 10
MIN_WIN_TRADES = 3


def equity_of(cash: float, positions: Sequence[tuple[float, float]]) -> float:
    """cash + sum(qty * price) over (qty, price) pairs."""
    return cash + sum(q * p for q, p in positions)


def return_since_launch(equity: float, starting_cash: float) -> float:
    return equity / starting_cash - 1.0


def sharpe(daily_equities: Sequence[float]) -> float | None:
    """Annualized Sharpe from daily equity closes; None until 10 daily returns exist."""
    rets = daily_returns(daily_equities)
    if len(rets) < MIN_SHARPE_DAYS:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    if sd == 0:
        return None
    return mean / sd * math.sqrt(252)


def max_drawdown(equities: Sequence[float]) -> float:
    """Largest peak-to-trough fall as a non-positive fraction (e.g. -0.12)."""
    peak = float("-inf")
    worst = 0.0
    for e in equities:
        peak = max(peak, e)
        if peak > 0:
            worst = min(worst, e / peak - 1.0)
    return worst


@dataclass(frozen=True, slots=True)
class Fill:
    side: str
    qty: float
    price: float


def closed_round_trips(fills: Sequence[Fill]) -> list[float]:
    """P&L of each closed round trip for one symbol, using average-cost accounting."""
    qty = 0.0
    cost = 0.0
    short_qty = 0.0
    proceeds = 0.0
    trips: list[float] = []
    for f in fills:
        if f.side == "BUY":
            qty += f.qty
            cost += f.qty * f.price
        elif f.side == "SHORT":
            short_qty += f.qty
            proceeds += f.qty * f.price
        elif f.side == "COVER" and short_qty > 0:
            avg = proceeds / short_qty
            trips.append((avg - f.price) * min(f.qty, short_qty))  # a short gains when it is bought back cheaper
            short_qty -= f.qty
            proceeds = avg * max(short_qty, 0.0)
            if short_qty <= 1e-12:
                short_qty, proceeds = 0.0, 0.0
        elif f.side == "SELL" and qty > 0:
            avg = cost / qty
            trips.append((f.price - avg) * min(f.qty, qty))
            qty -= f.qty
            cost = avg * max(qty, 0.0)
            if qty <= 1e-12:
                qty, cost = 0.0, 0.0
    return trips


def win_rate(trip_pnls: Sequence[float]) -> float | None:
    if len(trip_pnls) < MIN_WIN_TRADES:
        return None
    return sum(1 for p in trip_pnls if p > 0) / len(trip_pnls)


def today_change(equity: float, previous_close_equity: float | None) -> float | None:
    if previous_close_equity in (None, 0):
        return None
    assert previous_close_equity is not None
    return equity / previous_close_equity - 1.0
