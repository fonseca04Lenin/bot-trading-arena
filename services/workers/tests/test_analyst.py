import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from conftest import make_bars

from arena_workers.analyst.agent import run_agent
from arena_workers.analyst.guardrails import clean_text, mentions_outside_universe, review
from arena_workers.analyst.llm import CassetteClient, LLMResponse
from arena_workers.analyst.main import due
from arena_workers.analyst.tools import ToolBox
from arena_workers.analyst.views import FixtureView, compute_indicators

ROOT = Path(__file__).resolve().parents[3]
PF = {"cash": 100000.0, "equity": 100000.0, "positions": [], "open_slots": 5}


def toolbox_with(values: dict[str, float]) -> ToolBox:
    tb = ToolBox(FixtureView({"bars": {}, "portfolio": PF}))
    for k, v in values.items():
        tb.seen.setdefault(k, []).append(v)
    return tb


def decision(**kw: Any) -> dict[str, Any]:
    base = {"symbol": "AAPL", "action": "BUY", "target_pct": 0.05, "confidence": 0.5,
            "rationale": "AAPL RSI is 24.1.", "evidence": [{"metric": "rsi14", "value": 24.1}]}
    return {**base, **kw}


def test_valid_buy_passes() -> None:
    r = review({"decisions": [decision()]}, toolbox_with({"rsi14": 24.1}), PF, True)
    assert r.valid and [d.symbol for d in r.approved] == ["AAPL"]


@pytest.mark.parametrize("override,reason", [
    ({"evidence": [{"metric": "rsi14", "value": 12.0}]}, "unsupported_evidence"),
    ({"evidence": []}, "unsupported_evidence"),
    ({"symbol": "TSLA"}, "symbol_not_in_universe"),
    ({"target_pct": 0.2}, "target_pct_out_of_range"),
    ({"confidence": 1.5}, "confidence_out_of_range"),
    ({"rationale": "AAPL beats TSLA on RSI 24.1."}, "off_universe_text"),
])
def test_drops(override: dict[str, Any], reason: str) -> None:
    r = review({"decisions": [decision(**override)]}, toolbox_with({"rsi14": 24.1}), PF, True)
    assert r.valid and not r.approved and r.dropped[0][1] == reason


def test_schema_failure_holds_whole_run() -> None:
    r = review({"decisions": [{"symbol": "AAPL"}]}, toolbox_with({}), PF, True)
    assert not r.valid and not r.approved


def test_slots_cash_and_market_state() -> None:
    tb = toolbox_with({"rsi14": 24.1})
    full = {**PF, "positions": [{"symbol": s} for s in ("MSFT", "JPM", "XOM", "AMZN", "QQQ")]}
    assert review({"decisions": [decision()]}, tb, full, True).dropped[0][1] == "no_open_slots"
    poor = {**PF, "cash": 100.0}
    assert review({"decisions": [decision()]}, tb, poor, True).dropped[0][1] == "insufficient_cash"
    assert review({"decisions": [decision()]}, tb, PF, False).dropped[0][1] == "market_closed"
    assert review({"decisions": [decision(symbol="BTC/USD")]}, tb, PF, False).approved


def test_second_buy_respects_remaining_cash_and_slots() -> None:
    tb = toolbox_with({"rsi14": 24.1})
    pf = {**PF, "cash": 12000.0}
    r = review({"decisions": [decision(target_pct=0.10), decision(symbol="MSFT", target_pct=0.10)]}, tb, pf, True)
    assert len(r.approved) == 1 and r.dropped[0][1] == "insufficient_cash"


def test_text_cleaning() -> None:
    assert clean_text("**Bold**\n- item  x", 50) == "Bold - item x"
    assert len(clean_text("a" * 500, 240)) == 240
    assert mentions_outside_universe("TSLA is up") and not mentions_outside_universe("AAPL RSI is 24 ET")


def test_indicators_and_missing_data() -> None:
    assert "error" in compute_indicators(make_bars([1.0] * 10))
    assert compute_indicators(make_bars([float(i) for i in range(60)]))["sma50"] > 0


def test_cassette_exhaustion_is_an_error() -> None:
    c = CassetteClient([LLMResponse([{"type": "text", "text": "hi"}], "end_turn")])
    c.create("", [], [])
    with pytest.raises(RuntimeError):
        c.create("", [], [])


def test_no_submission_becomes_hold() -> None:
    c = CassetteClient([LLMResponse([{"type": "text", "text": "I pass."}], "end_turn")])
    res = run_agent(c, FixtureView({"bars": {}, "portfolio": PF}))
    assert not res.review.valid and not res.approved


def test_due_cadence() -> None:
    from datetime import UTC, datetime, timedelta
    now = datetime(2026, 3, 4, tzinfo=UTC)
    assert due(now, None, True)
    assert not due(now, now - timedelta(minutes=29), True) and due(now, now - timedelta(minutes=31), True)
    assert not due(now, now - timedelta(minutes=90), False) and due(now, now - timedelta(hours=2), False)


def test_eval_suite_replays_cleanly() -> None:
    scen = list((ROOT / "evals/analyst/scenarios").glob("*.json"))
    assert len(scen) >= 15
    out = subprocess.run([sys.executable, "-I", str(ROOT / "evals/analyst/run.py")], capture_output=True, text=True,
                         env={"PYTHONPATH": f"{ROOT}/evals/analyst:{ROOT}/services/workers", "PATH": ""})
    assert out.returncode == 0, out.stdout + out.stderr
    assert json.loads((ROOT / "evals/analyst/report.json").read_text())["pass_rate"] == 1.0
