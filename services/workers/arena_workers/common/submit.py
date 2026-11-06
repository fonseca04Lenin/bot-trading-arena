"""Persist a signal and hand it to the execution service."""

import json
import uuid
from typing import Any

import httpx
import psycopg

from .config import Settings
from .models import Signal


def record_signal(conn: psycopg.Connection[dict[str, Any]], bot_id: int, sig: Signal) -> uuid.UUID:
    sid = uuid.uuid4()
    conn.execute(
        """INSERT INTO signals (id, bot_id, symbol, side, target_pct, rationale, evidence, bar_ts)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (sid, bot_id, sig.symbol, sig.side, sig.target_pct, sig.rationale, json.dumps(sig.evidence), sig.bar_ts),
    )
    return sid


def post_order(client: httpx.Client, s: Settings, signal_id: uuid.UUID, sig: Signal) -> dict[str, Any]:
    r = client.post(
        f"{s.execution_url}/v1/orders",
        headers={"X-Arena-Key": s.arena_key},
        json={"signal_id": str(signal_id), "bot_slug": sig.bot_slug, "symbol": sig.symbol, "side": sig.side,
              "target_pct": str(sig.target_pct), "idempotency_key": f"sig-{signal_id}"},
        timeout=45,  # above the execution service's own 20s wait for a broker fill
    )
    r.raise_for_status()
    body: dict[str, Any] = r.json()
    return body
