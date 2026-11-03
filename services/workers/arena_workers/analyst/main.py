import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg

from ..common import db
from ..common.clock import equity_market_open, to_et
from ..common.config import Settings, load_settings
from ..common.models import Signal
from ..common.submit import post_order, record_signal
from .agent import RunResult, run_agent
from .llm import AnthropicClient, LLMClient
from .views import DbView

log = logging.getLogger("analyst")
MARKET_EVERY = timedelta(minutes=30)
OFF_HOURS_EVERY = timedelta(hours=2)


def due(now: datetime, last_run: datetime | None, market_open: bool) -> bool:
    gap = MARKET_EVERY if market_open else OFF_HOURS_EVERY
    return last_run is None or now - last_run >= gap


def calls_today(conn: psycopg.Connection[dict[str, Any]], now: datetime) -> int:
    start = to_et(now).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    row = conn.execute("SELECT count(*) AS n FROM agent_runs WHERE started_at >= %s", (start,)).fetchone()
    return int(row["n"]) if row else 0


def store_run(conn: psycopg.Connection[dict[str, Any]], model: str, res: RunResult, started: datetime,
              latency_ms: int) -> None:
    output = {"approved": [d.model_dump() for d in res.review.approved], "dropped": res.review.dropped,
              "market_note": res.review.market_note}
    conn.execute(
        """INSERT INTO agent_runs (id, started_at, model, prompt_version, input, output, valid, error,
                                   input_tokens, output_tokens, latency_ms) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (uuid.uuid4(), started, model, res.prompt_version, json.dumps(res.transcript, default=str),
         json.dumps(output), res.review.valid, res.review.error, res.input_tokens, res.output_tokens, latency_ms))
    if res.review.market_note:
        conn.execute("INSERT INTO market_notes (note) VALUES (%s)", (res.review.market_note,))


def run_once(conn: psycopg.Connection[dict[str, Any]], client: LLMClient, http: httpx.Client, s: Settings,
             now: datetime) -> RunResult | None:
    if calls_today(conn, now) >= s.agent_max_calls:
        log.warning("budget_exhausted: holding")
        return None
    bot = conn.execute("SELECT id FROM bots WHERE slug='analyst'").fetchone()
    assert bot
    forced = os.environ.get("ARENA_FORCE_MARKET_OPEN") == "1" and s.env != "production"
    view = DbView(conn, bot["id"], forced or equity_market_open(now))
    t0 = time.monotonic()
    try:
        res = run_agent(client, view)
    except Exception as exc:  # any model/transport failure becomes a logged HOLD
        log.error("agent run failed: %s", exc)
        from .guardrails import Review
        res = RunResult(Review(valid=False, error=f"exception: {exc}"))
    store_run(conn, s.agent_model, res, now, int((time.monotonic() - t0) * 1000))
    for d in res.approved:
        sig = Signal("analyst", d.symbol, d.action, d.target_pct if d.action == "BUY" else 0.0,  # type: ignore[arg-type]
                     d.rationale, now, [e.model_dump() for e in d.evidence])
        sid = record_signal(conn, bot["id"], sig)
        try:
            post_order(http, s, sid, sig)
        except httpx.HTTPError as exc:
            log.error("execution call failed: %s", exc)
    log.info("analyst run valid=%s approved=%d dropped=%s", res.review.valid, len(res.approved), res.review.dropped)
    return res


def main() -> None:
    db.configure_logging("analyst")
    s = load_settings()
    if not s.anthropic_key:
        log.error("ANTHROPIC_API_KEY not set; the analyst will idle and hold")
    client = AnthropicClient(s.agent_model, s.anthropic_key) if s.anthropic_key else None
    with db.connect() as conn, httpx.Client() as http:
        db.seed_bots(conn)
        while True:
            db.heartbeat(conn, "analyst", {"prompt_version": "v1", "model": s.agent_model})
            now = datetime.now(UTC)
            last = conn.execute("SELECT max(started_at) AS t FROM agent_runs").fetchone()
            forced = os.environ.get("ARENA_FORCE_MARKET_OPEN") == "1" and s.env != "production"
            if client and due(now, last["t"] if last else None, forced or equity_market_open(now)):
                run_once(conn, client, http, s, now)
            time.sleep(30)


def run() -> None:
    main()
