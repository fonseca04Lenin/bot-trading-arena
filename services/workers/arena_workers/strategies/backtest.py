"""Backtester that replays bars through the same Strategy classes used live (spec §9.4)."""

from collections.abc import Sequence
from dataclasses import dataclass

from ..common import metrics
from ..common.models import Bar, Position, Signal
from .base import Strategy

SLIPPAGE = 0.0002
MAX_POSITION_PCT = 0.10


@dataclass(frozen=True, slots=True)
class BacktestTrade:
    ts: str
    side: str
    qty: float
    price: float
    rationale: str


@dataclass(frozen=True, slots=True)
class BacktestResult:
    equity: list[tuple[str, float]]
    trades: list[BacktestTrade]
    signals: list[Signal]
    total_return: float
    max_drawdown: float
    sharpe: float | None
    win_rate: float | None


def generate_signals(strategy: Strategy, symbol: str, bars: Sequence[Bar]) -> list[Signal]:
    """Feed bars one by one, tracking a notional position as the live path does."""
    out: list[Signal] = []
    pos: Position | None = None
    for i in range(1, len(bars) + 1):
        sig = strategy.on_bar(symbol, bars[:i], pos)
        if sig is None:
            continue
        out.append(sig)
        pos = Position(symbol, 1.0, bars[i - 1].c) if sig.side == "BUY" else None
    return out


def run_backtest(
    strategy: Strategy, symbol: str, bars: Sequence[Bar], starting_cash: float = 100_000.0
) -> BacktestResult:
    cash = starting_cash
    pos: Position | None = None
    trades: list[BacktestTrade] = []
    signals: list[Signal] = []
    fills: list[metrics.Fill] = []
    curve: list[tuple[str, float]] = []
    for i, bar in enumerate(bars):
        sig = strategy.on_bar(symbol, bars[: i + 1], pos)
        if sig is not None:
            signals.append(sig)
            if sig.side == "BUY" and pos is None:
                px = bar.c * (1 + SLIPPAGE)
                pct = sig.target_pct if sig.target_pct > 0 else MAX_POSITION_PCT
                equity_now = cash
                qty = equity_now * pct / px
                cash -= qty * px
                pos = Position(symbol, qty, px)
                trades.append(BacktestTrade(bar.ts.isoformat(), "BUY", qty, px, sig.rationale))
                fills.append(metrics.Fill("BUY", qty, px))
            elif sig.side == "SELL" and pos is not None:
                px = bar.c * (1 - SLIPPAGE)
                cash += pos.qty * px
                trades.append(BacktestTrade(bar.ts.isoformat(), "SELL", pos.qty, px, sig.rationale))
                fills.append(metrics.Fill("SELL", pos.qty, px))
                pos = None
        eq = cash + (pos.qty * bar.c if pos else 0.0)
        curve.append((bar.ts.isoformat(), eq))
    values = [e for _, e in curve] or [starting_cash]
    trips = metrics.closed_round_trips(fills)
    return BacktestResult(
        equity=curve,
        trades=trades,
        signals=signals,
        total_return=values[-1] / starting_cash - 1.0,
        max_drawdown=metrics.max_drawdown(values),
        sharpe=metrics.sharpe(values),
        win_rate=metrics.win_rate(trips),
    )
