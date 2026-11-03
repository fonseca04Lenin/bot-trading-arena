"""A deterministic stand-in for the model, used to seed cassettes offline (`make eval-seed`).

It is labelled `source: "scripted"` in every cassette it writes. `make eval-live` re-records the same
scenarios against the real model and overwrites them with `source: "live"`.
"""

import json
from typing import Any

from arena_workers.analyst.llm import LLMResponse

UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "BTC/USD", "ETH/USD"]


def _use(i: int, name: str, args: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": f"toolu_{i}_{name}", "name": name, "input": args}


class ScriptedClient:
    def __init__(self, scenario: dict[str, Any]) -> None:
        self.s = scenario
        self.policy = scenario["policy"]
        self.step = 0

    def _results(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for m in messages:
            if m["role"] == "user" and isinstance(m["content"], list):
                for b in m["content"]:
                    if b.get("type") == "tool_result":
                        out[b["tool_use_id"]] = json.loads(b["content"])
        return out

    def create(self, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        self.step += 1
        if self.step == 1:
            return LLMResponse([_use(1, "get_portfolio", {})], "tool_use", 900, 40)
        if self.step == 2:
            calls = [_use(2, "get_indicators", {"symbol": s}) for s in UNIVERSE]
            for c in calls:
                c["id"] = f"toolu_2_{c['input']['symbol'].replace('/', '')}"
            return LLMResponse(calls, "tool_use", 1400, 120)
        res = self._results(messages)
        pf = next(v for k, v in res.items() if k.endswith("get_portfolio"))
        ind = {v["symbol"]: v for v in res.values() if "symbol" in v and "rsi14" in v or "error" in v and "symbol" in v}
        return LLMResponse([{"type": "tool_use", "id": "toolu_3_submit", "name": "submit_decisions",
                             "input": self._decide(pf, ind)}], "tool_use", 2600, 260)

    def _decide(self, pf: dict[str, Any], ind: dict[str, Any]) -> dict[str, Any]:
        held = {p["symbol"] for p in pf["positions"]}
        p = self.policy
        if p == "bad_schema":
            return {"decisions": "buy everything"}
        if p == "out_of_universe":
            return {"decisions": [self._d("TSLA", "BUY", 0.05, "TSLA looks strong at RSI 12.3.", [("rsi14", 12.3)])]}
        if p == "bad_evidence":
            return {"decisions": [self._d("AAPL", "BUY", 0.05, "AAPL is oversold with RSI 17.77.", [("rsi14", 17.77)])]}
        if p == "oversized":
            return {"decisions": [self._buy("AAPL", ind["AAPL"], pct=0.5)]}
        if p == "sell_unheld":
            return {"decisions": [{"symbol": "XOM", "action": "SELL", "target_pct": 0.0, "confidence": 0.6,
                                   "rationale": f"XOM RSI is {ind['XOM']['rsi14']}, so I would take profit.",
                                   "evidence": [{"metric": "rsi14", "value": ind["XOM"]["rsi14"]}]}]}
        decisions, slots_ok = [], pf["open_slots"] > 0 and pf["cash"] >= 0.05 * pf["equity"]
        for sym, i in ind.items():
            if "rsi14" not in i:
                continue
            if i["rsi14"] < 30 and sym not in held and (self.policy == "eager" or slots_ok):
                decisions.append(self._buy(sym, i, markdown=self.policy == "markdown"))
            elif i["rsi14"] > 70 and sym in held:
                decisions.append({"symbol": sym, "action": "SELL", "target_pct": 0.0, "confidence": 0.6,
                                  "rationale": f"{sym} RSI is {i['rsi14']} at {i['price']}, so the run looks stretched.",
                                  "evidence": [{"metric": "rsi14", "value": i["rsi14"]}, {"metric": "price", "value": i["price"]}]})
        return {"decisions": decisions, "market_note": "Quiet tape; the scripted policy held most names."}

    @staticmethod
    def _d(sym: str, action: str, pct: float, why: str, ev: list[tuple[str, float]]) -> dict[str, Any]:
        return {"symbol": sym, "action": action, "target_pct": pct, "confidence": 0.6, "rationale": why,
                "evidence": [{"metric": m, "value": v} for m, v in ev]}

    def _buy(self, sym: str, i: dict[str, Any], pct: float = 0.05, markdown: bool = False) -> dict[str, Any]:
        why = f"{sym} RSI fell to {i['rsi14']} at {i['price']}, so the drop looks overdone."
        if markdown:
            why = f"**{sym}** is oversold:\n\n- RSI at {i['rsi14']}\n- price {i['price']}"
        return self._d(sym, "BUY", pct, why, [("rsi14", i["rsi14"]), ("price", i["price"])])
