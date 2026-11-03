import json
import logging
import sys
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from .config import load_settings
from .models import Bar, Position

BOT_SEED: list[dict[str, Any]] = [
    {"slug": "crossover", "name": "The Crossover", "kind": "crossover", "broker": "alpaca_paper",
     "params": {"fast": 20, "slow": 50}, "silks": {"pattern": "quartered", "colors": ["ink", "spot"]}},
    {"slug": "rubber-band", "name": "The Rubber Band", "kind": "rubber-band", "broker": "sim",
     "params": {"period": 14, "buy_below": 30, "sell_above": 70},
     "silks": {"pattern": "hooped", "colors": ["ochre", "ink"]}},
    {"slug": "breakout", "name": "The Breakout", "kind": "breakout", "broker": "sim",
     "params": {"entry": 20, "exit": 10}, "silks": {"pattern": "chevron", "colors": ["slate", "paper"]}},
    {"slug": "index", "name": "The Index", "kind": "index", "broker": "sim",
     "params": {"risk_profile": "benchmark"}, "silks": {"pattern": "sash", "colors": ["olive", "paper"]}},
    {"slug": "analyst", "name": "The Analyst", "kind": "analyst", "broker": "sim",
     "params": {}, "silks": {"pattern": "diamonds", "colors": ["oxblood", "paper"]}},
]
STARTING_CASH = 100_000


def connect(autocommit: bool = True) -> psycopg.Connection[dict[str, Any]]:
    return psycopg.connect(load_settings().database_url, autocommit=autocommit, row_factory=dict_row)


def configure_logging(service: str) -> logging.Logger:
    class JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            return json.dumps({"ts": datetime.now(UTC).isoformat(), "service": service,
                               "level": record.levelname, "msg": record.getMessage()})

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    return logging.getLogger(service)


def seed_bots(conn: psycopg.Connection[dict[str, Any]]) -> None:
    for b in BOT_SEED:
        row = conn.execute(
            """INSERT INTO bots (slug, name, strategy_kind, params, silks, starting_cash, broker)
               VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (slug) DO NOTHING RETURNING id""",
            (b["slug"], b["name"], b["kind"], json.dumps(b["params"]), json.dumps(b["silks"]),
             STARTING_CASH, b["broker"]),
        ).fetchone()
        if row:
            conn.execute("INSERT INTO cash (bot_id, amount) VALUES (%s, %s)", (row["id"], STARTING_CASH))


def heartbeat(conn: psycopg.Connection[dict[str, Any]], service: str, info: dict[str, Any] | None = None) -> None:
    now = datetime.now(UTC)
    conn.execute(
        """INSERT INTO heartbeats (service, last_seen, info) VALUES (%s,%s,%s)
           ON CONFLICT (service) DO UPDATE SET last_seen = EXCLUDED.last_seen, info = EXCLUDED.info""",
        (service, now, json.dumps(info or {})),
    )
    conn.execute("INSERT INTO heartbeat_log (service, ts) VALUES (%s,%s) ON CONFLICT DO NOTHING", (service, now))


def upsert_bars(conn: psycopg.Connection[dict[str, Any]], symbol: str, timeframe: str, bars: Sequence[Bar]) -> None:
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO bars (symbol,timeframe,ts,o,h,l,c,v) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (symbol,timeframe,ts) DO UPDATE SET o=EXCLUDED.o,h=EXCLUDED.h,
               l=EXCLUDED.l,c=EXCLUDED.c,v=EXCLUDED.v""",
            [(symbol, timeframe, b.ts, b.o, b.h, b.l, b.c, b.v) for b in bars],
        )


def load_bars(conn: psycopg.Connection[dict[str, Any]], symbol: str, timeframe: str, limit: int,
              start: datetime | None = None, end: datetime | None = None) -> list[Bar]:
    rows = conn.execute(
        """SELECT ts,o,h,l,c,v FROM (
             SELECT ts,o,h,l,c,v FROM bars WHERE symbol=%s AND timeframe=%s
               AND (%s::timestamptz IS NULL OR ts >= %s) AND (%s::timestamptz IS NULL OR ts <= %s)
             ORDER BY ts DESC LIMIT %s) t ORDER BY ts""",
        (symbol, timeframe, start, start, end, end, limit),
    ).fetchall()
    return [Bar(r["ts"], float(r["o"]), float(r["h"]), float(r["l"]), float(r["c"]), float(r["v"])) for r in rows]


def load_position(conn: psycopg.Connection[dict[str, Any]], bot_id: int, symbol: str) -> Position | None:
    r = conn.execute("SELECT qty, avg_cost FROM positions WHERE bot_id=%s AND symbol=%s AND qty > 0",
                     (bot_id, symbol)).fetchone()
    return Position(symbol, float(r["qty"]), float(r["avg_cost"])) if r else None


def latest_price(conn: psycopg.Connection[dict[str, Any]], symbol: str) -> float | None:
    r = conn.execute(
        "SELECT c FROM bars WHERE symbol=%s AND timeframe IN ('1Min','5Min') ORDER BY ts DESC LIMIT 1",
        (symbol,)).fetchone()
    return float(r["c"]) if r else None


def run_forever(service: str, tick: Any, interval: float = 30.0) -> None:
    """Heartbeat plus a per-iteration callable; reconnects on DB errors."""
    log = configure_logging(service)
    while True:
        try:
            with connect() as conn:
                seed_bots(conn)
                while True:
                    heartbeat(conn, service)
                    tick(conn)
                    time.sleep(interval)
        except psycopg.Error as exc:
            log.error("database error: %s", exc)
            time.sleep(5)
