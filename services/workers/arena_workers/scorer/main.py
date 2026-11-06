import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from ..common import db, metrics
from ..common.universe import UNIVERSE
from ..report.daily import maybe_send_daily

log = logging.getLogger("scorer")


def snapshot_equity(conn: psycopg.Connection[dict[str, Any]], now: datetime | None = None) -> int:
    """Write one equity snapshot per bot: cash + positions marked to the latest price."""
    ts = (now or datetime.now(UTC)).replace(second=0, microsecond=0)
    prices = {sym: p for sym in UNIVERSE if (p := db.latest_price(conn, sym)) is not None}
    n = 0
    for bot in conn.execute("SELECT id FROM bots").fetchall():
        cash = conn.execute("SELECT amount FROM cash WHERE bot_id=%s", (bot["id"],)).fetchone()
        if cash is None:
            continue
        pos = conn.execute("SELECT symbol, qty, avg_cost FROM positions WHERE bot_id=%s AND qty <> 0",
                           (bot["id"],)).fetchall()
        held = [(float(p["qty"]), prices.get(p["symbol"], float(p["avg_cost"]))) for p in pos]
        eq = metrics.equity_of(float(cash["amount"]), held)
        conn.execute(
            """INSERT INTO equity_snapshots (bot_id, ts, equity) VALUES (%s,%s,%s)
               ON CONFLICT (bot_id, ts) DO UPDATE SET equity = EXCLUDED.equity""",
            (bot["id"], ts, round(eq, 4)))
        n += 1
    conn.execute("SELECT pg_notify('equity_tick', %s)", (ts.isoformat(),))
    return n


def prune_heartbeat_log(conn: psycopg.Connection[dict[str, Any]]) -> None:
    conn.execute("DELETE FROM heartbeat_log WHERE ts < %s", (datetime.now(UTC) - timedelta(days=31),))


SNAPSHOT_EVERY = timedelta(minutes=5)
_last_snapshot: datetime | None = None


def tick(conn: psycopg.Connection[dict[str, Any]]) -> None:
    global _last_snapshot
    now = datetime.now(UTC)
    maybe_send_daily(conn, now)
    if _last_snapshot is not None and now - _last_snapshot < SNAPSHOT_EVERY:
        return
    _last_snapshot = now
    n = snapshot_equity(conn, now)
    prune_heartbeat_log(conn)
    log.info("snapshots=%d", n)


def run() -> None:
    db.run_forever("scorer", tick, interval=30.0)
