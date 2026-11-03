"""Eval runner. Modes: replay (default, CI), seed (offline scripted cassettes), live (re-record with the real model)."""

import argparse
import json
import math
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arena_workers.analyst.agent import run_agent
from arena_workers.analyst.llm import AnthropicClient, CassetteClient, RecordingClient
from arena_workers.analyst.tools import ToolBox
from arena_workers.analyst.version import PROMPT_VERSION
from arena_workers.analyst.views import FixtureView
from arena_workers.common.universe import UNIVERSE

HERE = Path(__file__).parent
SCEN, CASS = HERE / "scenarios", HERE / "cassettes"
CHECKS = ["schema_valid", "no_out_of_universe", "no_limit_violations", "evidence_ok",
          "hold_when_data_missing", "no_buy_when_exhausted", "matches_expectation"]


def evaluate(spec: dict[str, Any], run: Any) -> dict[str, bool]:
    view = FixtureView(spec["view"])
    pf = view.portfolio()
    approved = run.review.approved
    tb = ToolBox(view)
    tb.call("get_portfolio", {})
    for s in UNIVERSE:
        tb.call("get_indicators", {"symbol": s})
    buys = [d for d in approved if d.action == "BUY"]
    missing = [s for s in UNIVERSE if not view.bars(s, "5Min", 100)]
    exhausted = pf["open_slots"] == 0 or pf["cash"] < 0.05 * pf["equity"]
    want: dict[str, str] = spec.get("expect", {})
    got = {d.symbol: d.action for d in approved}
    if "max_buys" in spec:
        expectation = len(buys) <= spec["max_buys"] and len(buys) >= 1
    else:
        expectation = all(got.get(s, "HOLD") == a for s, a in want.items()) and set(got) <= set(want)
    dropped = dict(run.review.dropped)
    expectation = expectation and all(dropped.get(s) == r for s, r in spec.get("dropped", {}).items())
    return {
        "schema_valid": run.review.valid == spec.get("run_valid", True),
        "no_out_of_universe": all(d.symbol in UNIVERSE for d in approved),
        "no_limit_violations": all(0.05 <= d.target_pct <= 0.10 for d in buys)
        and len(buys) <= pf["open_slots"] and sum(pf["equity"] * d.target_pct for d in buys) <= pf["cash"] + 1e-6,
        "evidence_ok": all(d.evidence and all(tb.supports(e.metric, e.value) for e in d.evidence) for d in approved),
        "hold_when_data_missing": not any(d.symbol in missing for d in approved),
        "no_buy_when_exhausted": not (exhausted and buys),
        "matches_expectation": expectation,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["replay", "seed", "live"], default="replay")
    ap.add_argument("--report", action="store_true", help="write REPORT.md and report.json")
    args = ap.parse_args()
    CASS.mkdir(exist_ok=True)
    rows: list[dict[str, Any]] = []
    source, model = "unknown", "unknown"
    for path in sorted(SCEN.glob("*.json")):
        spec = json.loads(path.read_text())
        cpath = CASS / path.name
        if args.mode == "replay":
            client: Any = CassetteClient.load(cpath)
            meta = json.loads(cpath.read_text())
            source, model = meta["source"], meta["model"]
        else:
            if args.mode == "seed":
                from scripted import ScriptedClient
                inner: Any = ScriptedClient(spec)
                source, model = "scripted", "scripted-policy"
            else:
                model = os.environ.get("AGENT_MODEL", "claude-sonnet-5-5")
                inner = AnthropicClient(model, os.environ["ANTHROPIC_API_KEY"])
                source = "live"
            client = RecordingClient(inner)
        run = run_agent(client, FixtureView(spec["view"]))
        if args.mode != "replay":
            client.save(cpath, source, model)
        checks = evaluate(spec, run)
        rows.append({"name": spec["name"], "description": spec["description"], "checks": checks,
                     "passed": all(checks.values()), "dropped": run.review.dropped,
                     "approved": [f"{d.action} {d.symbol}" for d in run.approved]})
    total = len(rows)
    passed = sum(r["passed"] for r in rows)
    per_check = {c: sum(r["checks"][c] for r in rows) / total for c in CHECKS}
    report = {"generated": datetime.now(UTC).isoformat(timespec="seconds"), "source": source, "model": model,
              "prompt_version": PROMPT_VERSION, "scenarios": total, "passed": passed,
              "pass_rate": passed / total, "per_check": per_check, "results": rows}
    for r in rows:
        print(("PASS " if r["passed"] else "FAIL ") + r["name"], "" if r["passed"] else [k for k, v in r["checks"].items() if not v])
    print(f"{passed}/{total} scenarios pass (source={source})")
    if args.report:
        (HERE / "report.json").write_text(json.dumps(report, indent=1) + "\n")
        lines = [f"# Analyst eval report", "", f"- Scenarios: {total}", f"- Pass rate: {passed}/{total} ({100 * passed / total:.0f}%)",
                 f"- Cassette source: `{source}` ({model}); prompt version `{PROMPT_VERSION}`",
                 f"- Generated: {report['generated']}", "", "| Check | Pass rate |", "|---|---|"]
        lines += [f"| {c} | {100 * v:.0f}% |" for c, v in per_check.items()]
        lines += ["", "| Scenario | Result | Approved | Dropped by guardrails |", "|---|---|---|---|"]
        lines += [f"| {r['name']} | {'pass' if r['passed'] else 'FAIL'} | {', '.join(r['approved']) or 'none'} | "
                  f"{', '.join(f'{s}: {why}' for s, why in r['dropped']) or 'none'} |" for r in rows]
        (HERE / "REPORT.md").write_text("\n".join(lines) + "\n")
    _ = math
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
