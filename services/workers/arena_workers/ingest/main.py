import asyncio
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from ..common import db
from ..common.clock import equity_market_open
from ..common.config import load_settings
from ..common.models import Bar
from ..common.universe import UNIVERSE, is_crypto
from .aggregate import FiveMinAggregator
from .sources import AlpacaRest, SyntheticWalk, alpaca_stream, synthetic_stream


def write_closed_bar(conn: psycopg.Connection[dict[str, Any]], symbol: str, bar: Bar) -> None:
    db.upsert_bars(conn, symbol, "5Min", [bar])
    conn.execute("SELECT pg_notify('bar_closed', %s)", (f"{symbol}|{bar.ts.isoformat()}",))


async def backfill_alpaca(conn: psycopg.Connection[dict[str, Any]], rest: AlpacaRest) -> None:
    now = datetime.now(UTC)
    for sym in UNIVERSE:
        db.upsert_bars(conn, sym, "5Min", await rest.bars(sym, "5Min", now - timedelta(days=90)))
        db.upsert_bars(conn, sym, "1Day", await rest.bars(sym, "1Day", now - timedelta(days=730)))


def backfill_synthetic(conn: psycopg.Connection[dict[str, Any]], walk: SyntheticWalk) -> None:
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    for sym in UNIVERSE:
        minute = walk.history(sym, 60 * 24 * 3, now)
        agg = FiveMinAggregator()
        closed = [b for m in minute if (b := agg.add(sym, m))]
        db.upsert_bars(conn, sym, "5Min", closed)
        db.upsert_bars(conn, sym, "1Day", _daily(walk, sym, now))


def _daily(walk: SyntheticWalk, sym: str, now: datetime) -> list[Bar]:
    out = []
    for i in range(500, 0, -1):
        b = walk.next_bar(sym, (now - timedelta(days=i)).replace(hour=0, minute=0))
        out.append(Bar(b.ts, b.o, b.h * 1.004, b.l * 0.996, b.c, b.v))
    return out


async def main() -> None:
    s = load_settings()
    log = db.configure_logging("ingest")
    if s.data_source == "synthetic" and s.env == "production":
        raise SystemExit("synthetic market data is not allowed in production")
    conn = db.connect()
    db.seed_bots(conn)
    walk = SyntheticWalk()
    if s.data_source == "alpaca":
        await backfill_alpaca(conn, AlpacaRest(s))
        stream = alpaca_stream(s, list(UNIVERSE))
    else:
        backfill_synthetic(conn, walk)
        speed = float(os.environ.get("SYNTHETIC_SPEED", "60"))
        stream = synthetic_stream(list(UNIVERSE), speed, walk, lambda: datetime.now(UTC))
    log.info("ingest running source=%s", s.data_source)
    agg = FiveMinAggregator()
    last_beat = 0.0
    async for symbol, bar in stream:
        db.upsert_bars(conn, symbol, "1Min", [bar])
        if not is_crypto(symbol) and s.data_source != "synthetic" and not equity_market_open(bar.ts):
            continue
        closed = agg.add(symbol, bar)
        if closed:
            write_closed_bar(conn, symbol, closed)
        loop_now = asyncio.get_running_loop().time()
        if loop_now - last_beat > 30:
            db.heartbeat(conn, "ingest", {"source": s.data_source})
            last_beat = loop_now


def run() -> None:
    asyncio.run(main())
