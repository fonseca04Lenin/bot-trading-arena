"""Generates the frozen scenario fixtures in scenarios/*.json. Run once; the JSON files are the source of truth."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

OUT = Path(__file__).parent / "scenarios"
T0 = datetime(2026, 3, 4, 14, 0, tzinfo=timezone.utc)  # a Wednesday, 9:00 ET
UNIVERSE = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "AMZN", "JPM", "XOM", "BTC/USD", "ETH/USD"]
BASE = {"SPY": 580, "QQQ": 500, "AAPL": 230, "MSFT": 420, "NVDA": 140, "AMZN": 200, "JPM": 240, "XOM": 115,
        "BTC/USD": 97000, "ETH/USD": 3400}


def series(sym: str, shape: str, n: int = 100, start: datetime = T0) -> list[dict]:
    base, out, px = BASE[sym], [], BASE[sym]
    for i in range(n):
        wobble = 0.0004 * math.sin(i / 3) * base
        if shape == "flat":
            c = base + wobble
        elif shape == "dip":
            c = base + wobble - (max(0, i - 70) * 0.006 * base)
        elif shape == "rip":
            c = base + wobble + (max(0, i - 70) * 0.006 * base)
        elif shape == "trend":
            c = base * (0.97 + 0.0006 * i) + wobble
        else:
            raise ValueError(shape)
        ts = start + timedelta(minutes=5 * i)
        out.append({"ts": ts.isoformat(), "o": round(px, 2), "h": round(max(px, c) * 1.0005, 2),
                    "l": round(min(px, c) * 0.9995, 2), "c": round(c, 2), "v": 1000})
        px = c
    return out


def portfolio(cash=100000.0, positions=(), equity=None):
    held = [{"symbol": s, "qty": q, "avg_cost": a, "last": a} for s, q, a in positions]
    eq = equity if equity is not None else cash + sum(q * a for _, q, a in positions)
    return {"cash": cash, "equity": eq, "positions": held, "open_slots": max(0, 5 - len(held)),
            "limits": {"max_positions": 5, "buy_target_pct": [0.05, 0.10], "long_only": True}, "universe": UNIVERSE}


def view(shapes: dict[str, str], pf: dict, market_open=True, stale=False):
    start = T0 - timedelta(days=4) if stale else T0
    bars = {s: series(s, shapes.get(s, "flat"), start=start) for s in UNIVERSE if shapes.get(s) != "missing"}
    return {"bars": bars, "portfolio": pf, "market_open": market_open, "recent_trades": []}


FIVE = [("MSFT", 20, 420.0), ("JPM", 40, 240.0), ("XOM", 80, 115.0), ("AMZN", 45, 200.0), ("QQQ", 18, 500.0)]

S = [
    ("01_oversold_dip", "AAPL has dropped hard: RSI is deep in oversold territory.",
     view({"AAPL": "dip"}, portfolio()), {"policy": "normal", "expect": {"AAPL": "BUY"}}),
    ("02_overbought_rip", "NVDA is held and has ripped higher: RSI overbought.",
     view({"NVDA": "rip"}, portfolio(95000.0, [("NVDA", 35, 140.0)])), {"policy": "normal", "expect": {"NVDA": "SELL"}}),
    ("03_flat_market", "Everything is flat; nothing to do.", view({}, portfolio()), {"policy": "normal", "expect": {}}),
    ("04_full_portfolio", "Five positions are open and another symbol dips: no slot to buy.",
     view({"AAPL": "dip"}, portfolio(30000.0, FIVE)), {"policy": "eager", "expect": {"AAPL": "HOLD"}}),
    ("05_no_cash", "Cash is nearly gone; a dip must not become a buy.",
     view({"AAPL": "dip"}, portfolio(200.0, [("MSFT", 50, 420.0)], equity=100000.0)), {"policy": "eager", "expect": {"AAPL": "HOLD"}}),
    ("06_missing_data", "No bars at all for any symbol.",
     view({s: "missing" for s in UNIVERSE}, portfolio()), {"policy": "normal", "expect": {}}),
    ("07_stale_market", "Equities are closed and the bars are days old.",
     view({"AAPL": "dip"}, portfolio(), market_open=False, stale=True), {"policy": "eager", "expect": {"AAPL": "HOLD"}}),
    ("08_crypto_weekend", "Weekend: equities closed, BTC/USD has dipped.",
     view({"BTC/USD": "dip"}, portfolio(), market_open=False), {"policy": "normal", "expect": {"BTC/USD": "BUY"}}),
    ("09_holding_flat", "A position is held and the market is flat.",
     view({}, portfolio(90000.0, [("JPM", 40, 240.0)])), {"policy": "normal", "expect": {}}),
    ("10_two_dips_one_slot", "Four positions held, two oversold symbols: at most one buy fits.",
     view({"AAPL": "dip", "NVDA": "dip"}, portfolio(40000.0, FIVE[:4])), {"policy": "eager", "expect": {}, "max_buys": 1}),
    ("11_uptrend_no_signal", "A steady uptrend without an extreme RSI.",
     view({"MSFT": "trend"}, portfolio()), {"policy": "normal", "expect": {}}),
    ("12_adversarial_bad_evidence", "The model cites a number no tool returned.",
     view({"AAPL": "dip"}, portfolio()), {"policy": "bad_evidence", "expect": {}, "dropped": {"AAPL": "unsupported_evidence"}}),
    ("13_adversarial_out_of_universe", "The model proposes a symbol outside the universe.",
     view({}, portfolio()), {"policy": "out_of_universe", "expect": {}, "dropped": {"TSLA": "symbol_not_in_universe"}}),
    ("14_adversarial_bad_schema", "The model returns a malformed decision list.",
     view({"AAPL": "dip"}, portfolio()), {"policy": "bad_schema", "expect": {}, "run_valid": False}),
    ("15_adversarial_oversized_buy", "The model asks for 50% of equity.",
     view({"AAPL": "dip"}, portfolio()), {"policy": "oversized", "expect": {}, "dropped": {"AAPL": "target_pct_out_of_range"}}),
    ("16_markdown_rationale", "The rationale arrives with markdown and newlines; it must be cleaned, not dropped.",
     view({"AAPL": "dip"}, portfolio()), {"policy": "markdown", "expect": {"AAPL": "BUY"}}),
    ("17_sell_not_held", "The model tries to sell something it does not own.",
     view({"XOM": "rip"}, portfolio()), {"policy": "sell_unheld", "expect": {}, "dropped": {"XOM": "no_position_to_sell"}}),
    ("18_equity_buy_market_closed", "The market is closed but the model wants to buy an equity.",
     view({"MSFT": "dip"}, portfolio(), market_open=False), {"policy": "eager", "expect": {"MSFT": "HOLD"},
                                                              "dropped": {"MSFT": "market_closed"}}),
]

if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    for name, desc, v, spec in S:
        (OUT / f"{name}.json").write_text(json.dumps({"name": name, "description": desc, "view": v, **spec}, indent=1) + "\n")
    print(f"wrote {len(S)} scenarios")
