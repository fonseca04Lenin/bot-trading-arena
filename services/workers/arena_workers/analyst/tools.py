"""The four read-only tools. Results are remembered so the evidence check can verify cited numbers."""

import math
from typing import Any

from ..common.universe import UNIVERSE
from .views import MarketView, compute_indicators

TOOLS: list[dict[str, Any]] = [
    {"name": "get_bars", "description": "Recent OHLC bars for a universe symbol (newest last).",
     "input_schema": {"type": "object", "properties": {
         "symbol": {"type": "string"}, "timeframe": {"type": "string", "enum": ["5Min", "1Day"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "required": ["symbol", "timeframe"]}},
    {"name": "get_portfolio", "description": "Cash, positions, equity, open slots, risk limits and the symbol universe.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "get_indicators", "description": "Latest price, SMA20, SMA50, RSI14 and 20-bar high/low for a symbol (5-minute bars).",
     "input_schema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}},
    {"name": "get_recent_trades", "description": "Your own recent decisions and their outcomes.",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 10}}}},
    {"name": "submit_decisions", "description": "Submit your final decisions. Call exactly once, last.",
     "input_schema": {"type": "object", "properties": {
         "decisions": {"type": "array", "items": {"type": "object", "properties": {
             "symbol": {"type": "string"}, "action": {"type": "string", "enum": ["BUY", "SELL", "HOLD"]},
             "target_pct": {"type": "number"}, "confidence": {"type": "number"},
             "rationale": {"type": "string"},
             "evidence": {"type": "array", "items": {"type": "object", "properties": {
                 "metric": {"type": "string"}, "value": {"type": "number"}}, "required": ["metric", "value"]}}},
             "required": ["symbol", "action", "confidence", "rationale"]}},
         "market_note": {"type": "string"}}, "required": ["decisions"]}},
]


class ToolBox:
    def __init__(self, view: MarketView) -> None:
        self.view = view
        self.seen: dict[str, list[float]] = {}  # lowercase metric key -> values returned by tools

    def _remember(self, obj: Any, key: str = "") -> None:
        if isinstance(obj, bool):
            return
        if isinstance(obj, (int, float)):
            self.seen.setdefault(key.lower(), []).append(float(obj))
        elif isinstance(obj, dict):
            for k, v in obj.items():
                self._remember(v, str(k))
        elif isinstance(obj, list):
            for v in obj:
                self._remember(v, key)

    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        try:
            result = self._dispatch(name, args)
        except (KeyError, ValueError, TypeError) as exc:
            return {"error": f"bad tool call: {exc}"}
        self._remember(result)
        return result

    def _dispatch(self, name: str, a: dict[str, Any]) -> dict[str, Any]:
        if name == "get_portfolio":
            return self.view.portfolio()
        if name == "get_recent_trades":
            return {"trades": self.view.recent_trades(min(int(a.get("limit", 10)), 10))}
        sym = str(a["symbol"])
        if sym not in UNIVERSE:
            raise ValueError(f"{sym} is not in the universe")
        if name == "get_indicators":
            return {"symbol": sym, **compute_indicators(self.view.bars(sym, "5Min", 100))}
        if name == "get_bars":
            tf = str(a["timeframe"])
            if tf not in ("5Min", "1Day"):
                raise ValueError("timeframe must be 5Min or 1Day")
            bars = self.view.bars(sym, tf, min(int(a.get("limit", 20)), 100))
            return {"symbol": sym, "timeframe": tf, "bars": [
                {"ts": b.ts.isoformat(), "o": round(b.o, 2), "h": round(b.h, 2), "l": round(b.l, 2), "c": round(b.c, 2)}
                for b in bars]}
        raise ValueError(f"unknown tool {name}")

    def supports(self, metric: str, value: float) -> bool:
        """True if `value` equals (within rounding) a number a tool returned; keyed by metric name when known."""
        pool = self.seen.get(metric.lower())
        if pool is None:
            pool = [v for vs in self.seen.values() for v in vs]
        return any(math.isclose(value, v, rel_tol=1e-3, abs_tol=0.011) for v in pool)
