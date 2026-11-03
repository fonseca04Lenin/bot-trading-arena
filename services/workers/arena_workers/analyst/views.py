"""Read-only market views the agent's tools read from: Postgres in production, fixtures in evals."""

from collections.abc import Sequence
from typing import Any, Protocol

from ..common import indicators as ind
from ..common.models import Bar
from ..common.universe import UNIVERSE


class MarketView(Protocol):
    def bars(self, symbol: str, timeframe: str, limit: int) -> list[Bar]: ...
    def portfolio(self) -> dict[str, Any]: ...
    def recent_trades(self, limit: int) -> list[dict[str, Any]]: ...
    def market_open(self) -> bool: ...


def compute_indicators(bars: Sequence[Bar]) -> dict[str, Any]:
    closes = [b.c for b in bars]
    out = {"price": closes[-1] if closes else None, "sma20": ind.sma(closes, 20), "sma50": ind.sma(closes, 50),
           "rsi14": ind.rsi(closes, 14), "high20": ind.highest([b.h for b in bars], 20),
           "low20": ind.lowest([b.l for b in bars], 20)}
    if any(v is None for v in out.values()):
        return {"error": "insufficient data", "bars": len(bars)}
    return {k: round(float(v), 2) for k, v in out.items() if v is not None}


class FixtureView:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def bars(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        from datetime import datetime
        raw = self.data["bars"].get(symbol, [])
        return [Bar(datetime.fromisoformat(r["ts"]), r["o"], r["h"], r["l"], r["c"], r.get("v", 0)) for r in raw][-limit:]

    def portfolio(self) -> dict[str, Any]:
        out: dict[str, Any] = self.data["portfolio"]
        return out

    def recent_trades(self, limit: int) -> list[dict[str, Any]]:
        return list(self.data.get("recent_trades", []))[:limit]

    def market_open(self) -> bool:
        return bool(self.data.get("market_open", True))


class DbView:
    def __init__(self, conn: Any, bot_id: int, now_open: bool) -> None:
        self.conn, self.bot_id, self._open = conn, bot_id, now_open

    def bars(self, symbol: str, timeframe: str, limit: int) -> list[Bar]:
        from ..common import db
        return db.load_bars(self.conn, symbol, timeframe, limit)

    def portfolio(self) -> dict[str, Any]:
        from ..common import db, metrics
        cash = float(self.conn.execute("SELECT amount FROM cash WHERE bot_id=%s", (self.bot_id,)).fetchone()["amount"])
        pos = self.conn.execute("SELECT symbol, qty, avg_cost FROM positions WHERE bot_id=%s AND qty>0",
                                (self.bot_id,)).fetchall()
        held = []
        for p in pos:
            px = db.latest_price(self.conn, p["symbol"]) or float(p["avg_cost"])
            held.append({"symbol": p["symbol"], "qty": float(p["qty"]), "avg_cost": round(float(p["avg_cost"]), 2),
                         "last": round(px, 2)})
        eq = metrics.equity_of(cash, [(h["qty"], h["last"]) for h in held])
        return {"cash": round(cash, 2), "equity": round(eq, 2), "positions": held,
                "open_slots": max(0, 5 - len(held)),
                "limits": {"max_positions": 5, "buy_target_pct": [0.05, 0.10], "long_only": True},
                "universe": list(UNIVERSE)}

    def recent_trades(self, limit: int) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT o.submitted_at, o.symbol, o.side, o.status, s.rationale FROM orders o
               JOIN signals s ON s.id=o.signal_id WHERE o.bot_id=%s ORDER BY o.submitted_at DESC LIMIT %s""",
            (self.bot_id, limit)).fetchall()
        return [{"ts": r["submitted_at"].isoformat(), "symbol": r["symbol"], "side": r["side"],
                 "status": r["status"], "rationale": r["rationale"]} for r in rows]

    def market_open(self) -> bool:
        return self._open
