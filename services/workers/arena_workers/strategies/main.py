import logging
import time
from datetime import UTC, datetime, timedelta
from datetime import time as dtime
from typing import Any

import httpx
import psycopg

from ..common import db
from ..common.clock import to_et
from ..common.config import load_settings
from ..common.models import Bar
from ..common.submit import post_order, record_signal
from ..common.universe import BENCHMARK_SYMBOL
from .forecast import Forecaster, load_forecaster
from .forecast_trader import ForecastTrader
from .quant import StatArb
from .rules import DAILY, LOOKBACK_BARS, build_strategy

RULE_KINDS = ("crossover", "rubber-band", "breakout", "index", "scorecard", "stat-arb", "orb", "kronos")
STALE_AFTER = timedelta(minutes=12)  # a forecast on an old candle is a forecast of the past
# Bots on daily candles decide once a day, on the candle that closes at 15:50 ET. By then the day's candle is
# all but final and the market is still open to fill the order. Crypto uses the same clock, weekends included.
DAILY_DECISION = dtime(15, 45)
log = logging.getLogger("strategies")


def is_daily_decision(ts: datetime) -> bool:
    return to_et(ts).time().replace(second=0, microsecond=0) == DAILY_DECISION


def _stale(bars: list[Bar]) -> bool:
    return not bars or datetime.now(UTC) - bars[-1].ts > STALE_AFTER


def _recently_ordered(conn: psycopg.Connection[dict[str, Any]], bot_id: int, symbol: str, side: str) -> bool:
    """Skip a repeat of a signal the execution service would only refuse for the 5-minute cooldown."""
    row = conn.execute(
        """SELECT 1 FROM orders WHERE bot_id=%s AND symbol=%s AND side=%s
           AND submitted_at > now() - interval '5 minutes' LIMIT 1""", (bot_id, symbol, side)).fetchone()
    return row is not None


def process_bar(conn: psycopg.Connection[dict[str, Any]], client: httpx.Client, symbol: str,
                forecaster: Forecaster | None = None) -> int:
    """Run every rule bot on the newly closed bar for `symbol`; returns signals emitted."""
    s = load_settings()
    bots = conn.execute("SELECT id, slug, strategy_kind, params FROM bots WHERE strategy_kind = ANY(%s)",
                        (list(RULE_KINDS),)).fetchall()
    loaded: dict[tuple[str, int], list[Bar]] = {}  # bots share a load when they want the same history

    def history(sym: str, n: int) -> list[Bar]:
        if (sym, n) not in loaded:
            loaded[sym, n] = db.load_bars(conn, sym, "5Min", n)
        return loaded[sym, n]

    bars = history(symbol, LOOKBACK_BARS)
    daily: list[Bar] | None = None
    emitted = 0
    for bot in bots:
        strat = build_strategy(bot["strategy_kind"], bot["params"], forecaster)
        held = db.load_position(conn, bot["id"], symbol)
        want = getattr(strat, "history_bars", LOOKBACK_BARS)
        if getattr(strat, "timeframe", "5Min") == DAILY:
            if not bars or _stale(bars) or not is_daily_decision(bars[-1].ts):
                continue
            daily = daily if daily is not None else db.load_daily(conn, symbol, 260)
            sig = strat.on_bar(symbol, daily[-want:], held)
        elif isinstance(strat, ForecastTrader):
            long_bars = history(symbol, want)
            if _stale(long_bars):
                continue
            sig = strat.on_bar(symbol, long_bars, held)
        elif isinstance(strat, StatArb):
            sig = strat.on_bar(symbol, history(symbol, want), held, benchmark=history(BENCHMARK_SYMBOL, want))
        else:
            sig = strat.on_bar(symbol, bars, held)
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
        forecaster = load_forecaster()
        log.info("forecast model %s", "loaded" if forecaster else "not loaded")
        listener.execute("LISTEN bar_closed")
        log.info("strategy worker listening")
        last_beat = 0.0
        while True:
            for note in listener.notifies(timeout=5.0, stop_after=50):
                symbol = note.payload.split("|")[0]
                n = process_bar(conn, client, symbol, forecaster)
                log.info("bar_closed %s signals=%d", symbol, n)
            if time.monotonic() - last_beat > 30:
                db.heartbeat(conn, "strategies")
                last_beat = time.monotonic()


def run() -> None:
    main()
