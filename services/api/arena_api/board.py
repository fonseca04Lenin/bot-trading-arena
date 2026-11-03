"""Leaderboard, equity series, trades and status queries shared by the routes."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from arena_workers.common import metrics
from arena_workers.common.clock import ET, to_et
from arena_workers.common.universe import UNIVERSE

from . import db

RANGES = {"1D": timedelta(days=1), "1W": timedelta(weeks=1), "1M": timedelta(days=31)}
MAX_POINTS = 300


def f(x: Any) -> float | None:
    return None if x is None else float(x)


def downsample(points: list[tuple[str, float]], limit: int = MAX_POINTS) -> list[tuple[str, float]]:
    if len(points) <= limit:
        return points
    step = (len(points) - 1) / (limit - 1)
    return [points[round(i * step)] for i in range(limit)]


async def equity_series(bot_id: int, rng: str) -> list[tuple[str, float]]:
    since = None if rng == "ALL" else datetime.now(UTC) - RANGES.get(rng, RANGES["1D"])
    rows = await db.fetch(
        "SELECT ts, equity FROM equity_snapshots WHERE bot_id=%s AND (%s::timestamptz IS NULL OR ts >= %s) ORDER BY ts",
        bot_id, since, since)
    return downsample([(r["ts"].isoformat(), float(r["equity"])) for r in rows])


def daily_closes(rows: list[dict[str, Any]]) -> list[float]:
    """Last snapshot of each Eastern calendar day."""
    by_day: dict[Any, float] = {}
    for r in rows:
        by_day[to_et(r["ts"]).date()] = float(r["equity"])
    return list(by_day.values())


async def bot_metrics(bot: dict[str, Any]) -> dict[str, Any]:
    snaps = await db.fetch("SELECT ts, equity FROM equity_snapshots WHERE bot_id=%s ORDER BY ts", bot["id"])
    start = float(bot["starting_cash"])
    equity = float(snaps[-1]["equity"]) if snaps else start
    today = to_et(datetime.now(UTC)).date()
    prior = [s for s in snaps if to_et(s["ts"]).date() < today]
    prev_close = float(prior[-1]["equity"]) if prior else (start if snaps else None)
    fills = await db.fetch(
        """SELECT o.symbol, o.side, f.qty, f.price FROM fills f JOIN orders o ON o.id=f.order_id
           WHERE o.bot_id=%s ORDER BY f.filled_at""", bot["id"])
    trips: list[float] = []
    for sym in {r["symbol"] for r in fills}:
        trips += metrics.closed_round_trips(
            [metrics.Fill(r["side"], float(r["qty"]), float(r["price"])) for r in fills if r["symbol"] == sym])
    cutoff = datetime.now(UTC) - timedelta(days=30)
    spark = downsample([(s["ts"].isoformat(), float(s["equity"])) for s in snaps if s["ts"] >= cutoff], 30)
    n_trades = await db.fetchone("SELECT count(*) AS n FROM orders WHERE bot_id=%s AND status='filled'", bot["id"])
    return {
        "equity": equity,
        "return": metrics.return_since_launch(equity, start),
        "today": metrics.today_change(equity, prev_close),
        "sharpe": metrics.sharpe(daily_closes(snaps)),
        "max_drawdown": metrics.max_drawdown([float(s["equity"]) for s in snaps]),
        "win_rate": metrics.win_rate(trips),
        "trades": int(n_trades["n"]) if n_trades else 0,
        "sparkline": [v for _, v in spark],
    }


def bot_row(b: dict[str, Any]) -> dict[str, Any]:
    from .copy import BOT_COPY
    return {"slug": b["slug"], "name": b["name"], "silks": b["silks"], "broker": b["broker"],
            "description": BOT_COPY.get(b["slug"], ""), "starting_cash": float(b["starting_cash"])}


async def leaderboard() -> list[dict[str, Any]]:
    bots = await db.fetch("SELECT * FROM bots ORDER BY id")
    rows = [{**bot_row(b), **await bot_metrics(b)} for b in bots]
    rows.sort(key=lambda r: r["return"], reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


TRADE_SELECT = """
SELECT o.id, o.submitted_at AS ts, o.symbol, o.side, o.qty, o.status, o.reject_reason, o.broker, o.latency_ms,
       b.slug AS bot_slug, b.name AS bot_name, b.silks, s.rationale, s.evidence, s.target_pct,
       (SELECT price FROM fills f WHERE f.order_id=o.id ORDER BY filled_at LIMIT 1) AS price
FROM orders o JOIN bots b ON b.id=o.bot_id JOIN signals s ON s.id=o.signal_id"""


def trade_json(r: dict[str, Any]) -> dict[str, Any]:
    return {"id": str(r["id"]), "ts": r["ts"].isoformat(), "symbol": r["symbol"], "side": r["side"],
            "qty": f(r["qty"]), "price": f(r["price"]), "status": r["status"], "reject_reason": r["reject_reason"],
            "broker": r["broker"], "latency_ms": r["latency_ms"], "bot_slug": r["bot_slug"],
            "bot_name": r["bot_name"], "silks": r["silks"], "rationale": r["rationale"],
            "evidence": r["evidence"] if isinstance(r["evidence"], list) else json.loads(r["evidence"])}


async def trades(bot: str | None = None, symbol: str | None = None, before: datetime | None = None,
                 limit: int = 20) -> list[dict[str, Any]]:
    rows = await db.fetch(
        TRADE_SELECT + """ WHERE (%s::text IS NULL OR b.slug=%s) AND (%s::text IS NULL OR o.symbol=%s)
        AND (%s::timestamptz IS NULL OR o.submitted_at < %s) ORDER BY o.submitted_at DESC LIMIT %s""",
        bot, bot, symbol, symbol, before, before, limit)
    return [trade_json(r) for r in rows]


async def ticker() -> list[dict[str, Any]]:
    out = []
    now = datetime.now(UTC)
    for sym in UNIVERSE:
        last = await db.fetchone(
            "SELECT c, ts FROM bars WHERE symbol=%s AND timeframe IN ('1Min','5Min') ORDER BY ts DESC LIMIT 1", sym)
        if not last:
            continue
        ref = await db.fetchone(
            "SELECT c FROM bars WHERE symbol=%s AND timeframe='5Min' AND ts <= %s ORDER BY ts DESC LIMIT 1",
            sym, min(last["ts"], now) - timedelta(hours=24))
        price = float(last["c"])
        chg = price / float(ref["c"]) - 1 if ref else None
        out.append({"symbol": sym, "price": price, "change": chg})
    return out


async def last_bar_time() -> datetime | None:
    r = await db.fetchone("SELECT max(ts) AS ts FROM bars WHERE timeframe IN ('1Min','5Min')")
    return r["ts"] if r else None


async def uptime() -> dict[str, Any]:
    """30-day uptime per service from heartbeat gaps, in 1-minute buckets."""
    rows = await db.fetch(
        """SELECT service, count(DISTINCT date_bin('1 minute', ts, TIMESTAMPTZ '2000-01-01')) AS seen,
                  min(ts) AS first FROM heartbeat_log WHERE ts > now() - interval '30 days' GROUP BY service""")
    per: dict[str, float] = {}
    now = datetime.now(UTC)
    for r in rows:
        expected = max(1.0, (now - r["first"]).total_seconds() / 60 + 1)
        per[r["service"]] = min(1.0, float(r["seen"]) / expected)
    return {"per_service": per, "overall": (sum(per.values()) / len(per)) if per else None}


def eval_report() -> dict[str, Any] | None:
    import os
    path = Path(os.environ.get("EVALS_DIR", Path(__file__).resolve().parents[3] / "evals" / "analyst")) / "report.json"
    try:
        data: dict[str, Any] = json.loads(path.read_text())
        return data
    except (OSError, ValueError):
        return None


async def agent_budget() -> dict[str, Any]:
    import os
    day_start = to_et(datetime.now(UTC)).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    r = await db.fetchone("SELECT count(*) AS n FROM agent_runs WHERE started_at >= %s", day_start)
    return {"calls_today": int(r["n"]) if r else 0,
            "max_calls": int(os.environ.get("AGENT_MAX_CALLS_PER_DAY", "30"))}


async def status() -> dict[str, Any]:
    beats = await db.fetch("SELECT service, last_seen, info FROM heartbeats ORDER BY service")
    now = datetime.now(UTC)
    lat = await db.fetchone(
        """SELECT percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::float8 AS p95,
                  count(*) FILTER (WHERE status='filled') AS filled, count(*) AS total
           FROM orders WHERE latency_ms IS NOT NULL""")
    totals = await db.fetchone("SELECT count(*) AS n FROM orders")
    return {
        "services": [{"service": b["service"], "last_seen": b["last_seen"].isoformat(),
                      "healthy": (now - b["last_seen"]).total_seconds() < 120} for b in beats],
        "uptime": await uptime(),
        "p95_signal_to_submit_ms": lat["p95"] if lat else None,
        "total_orders": int(totals["n"]) if totals else 0,
        "eval": eval_report(),
        "tz": str(ET),
    }
