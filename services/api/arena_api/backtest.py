import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from arena_workers.common import db as wdb
from arena_workers.common.universe import UNIVERSE
from arena_workers.strategies.backtest import run_backtest
from arena_workers.strategies.rules import build_strategy
from pydantic import BaseModel, Field, model_validator

from . import db

TIME_LIMIT = 3.0
MAX_SPAN = timedelta(days=731)


class BacktestRequest(BaseModel):
    strategy_slug: Literal["crossover", "rubber-band", "breakout", "index"]
    symbol: str
    start: datetime
    end: datetime
    params: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check(self) -> "BacktestRequest":
        if self.symbol not in UNIVERSE:
            raise ValueError("symbol is not in the universe")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > MAX_SPAN:
            raise ValueError("range may be at most 2 years")
        return self


def _compute(req: BacktestRequest, rows: list[Any]) -> dict[str, Any]:
    from arena_workers.common.models import Bar
    bars = [Bar(r["ts"], float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]), float(r["v"])) for r in rows]
    res = run_backtest(build_strategy(req.strategy_slug, req.params), req.symbol, bars)
    return {
        "equity": [{"ts": t, "equity": e} for t, e in res.equity],
        "trades": [t.__dict__ for t in res.trades],
        "metrics": {"return": res.total_return, "max_drawdown": res.max_drawdown,
                    "sharpe": res.sharpe, "win_rate": res.win_rate, "trades": len(res.trades), "bars": len(bars)},
    }


async def run(req: BacktestRequest) -> dict[str, Any]:
    start = req.start if req.start.tzinfo else req.start.replace(tzinfo=UTC)
    end = req.end if req.end.tzinfo else req.end.replace(tzinfo=UTC)
    rows = await db.fetch(
        "SELECT ts,o,h,l,c,v FROM bars WHERE symbol=%s AND timeframe='1Day' AND ts BETWEEN %s AND %s ORDER BY ts",
        req.symbol, start, end)
    if len(rows) < 2:
        raise ValueError("no daily bars for that symbol and range")
    return await asyncio.wait_for(asyncio.to_thread(_compute, req, rows), TIME_LIMIT)


_ = wdb
