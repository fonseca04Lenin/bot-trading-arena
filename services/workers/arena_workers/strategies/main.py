import logging
import time
from typing import Any

import httpx
import psycopg

from ..common import db
from ..common.config import load_settings
from ..common.submit import post_order, record_signal
from ..common.universe import BENCHMARK_SYMBOL
from .quant import StatArb
from .rules import LOOKBACK_BARS, build_strategy

RULE_KINDS = ("crossover", "rubber-band", "breakout", "index", "scorecard", "stat-arb", "orb")
log = logging.getLogger("strategies")


def _recently_ordered(conn: psycopg.Connection[dict[str, Any]], bot_id: int, symbol: str, side: str) -> bool:
    """Skip a repeat of a signal the execution service would only refuse for the 5-minute cooldown."""
    row = conn.execute(
        """SELECT 1 FROM orders WHERE bot_id=%s AND symbol=%s AND side=%s
           AND submitted_at > now() - interval '5 minutes' LIMIT 1""", (bot_id, symbol, side)).fetchone()
    return row is not None


def process_bar(conn: psycopg.Connection[dict[str, Any]], client: httpx.Client, symbol: str) -> int:
    """Run every rule bot on the newly closed bar for `symbol`; returns signals emitted."""
    s = load_settings()
    bots = conn.execute("SELECT id, slug, strategy_kind, params FROM bots WHERE strategy_kind = ANY(%s)",
                        (list(RULE_KINDS),)).fetchall()
    bars = db.load_bars(conn, symbol, "5Min", LOOKBACK_BARS)
    bench = db.load_bars(conn, BENCHMARK_SYMBOL, "5Min", LOOKBACK_BARS)
    emitted = 0
    for bot in bots:
        strat = build_strategy(bot["strategy_kind"], bot["params"])
        held = db.load_position(conn, bot["id"], symbol)
        sig = (strat.on_bar(symbol, bars, held, benchmark=bench) if isinstance(strat, StatArb)
               else strat.on_bar(symbol, bars, held))
        if sig is None or _recently_ordered(conn, bot["id"], sig.symbol, sig.side):
            continue
        sid = record_signal(conn, bot["id"], sig)
        try:
            post_order(client, s, sid, sig)
        except httpx.HTTPError as exc:
            log.error("execution call failed bot=%s symbol=%s: %s", bot["slug"], symbol, exc)
        emitted += 1
    return emitted


def main() -> None:
    log = db.configure_logging("strategies")
    # Separate connections: running queries on the LISTEN connection mid-iteration would deadlock it.
    with db.connect() as listener, db.connect() as conn, httpx.Client() as client:
        db.seed_bots(conn)
        listener.execute("LISTEN bar_closed")
        log.info("strategy worker listening")
        last_beat = 0.0
        while True:
            for note in listener.notifies(timeout=5.0, stop_after=50):
                symbol = note.payload.split("|")[0]
                n = process_bar(conn, client, symbol)
                log.info("bar_closed %s signals=%d", symbol, n)
            if time.monotonic() - last_beat > 30:
                db.heartbeat(conn, "strategies")
                last_beat = time.monotonic()


def run() -> None:
    main()
