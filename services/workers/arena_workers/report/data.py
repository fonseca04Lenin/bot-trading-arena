"""Collect one trading day's numbers for the private daily report. Read-only queries."""

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any

import psycopg

from ..common import db
from ..common.clock import ET


@dataclass(slots=True)
class BotDay:
    slug: str
    name: str
    equity: float
    prev_equity: float
    starting_cash: float
    trades: int = 0
    filled: int = 0
    rejected: int = 0
    positions: list[tuple[str, float, float, float]] = field(default_factory=list)  # symbol, qty, avg_cost, last

    @property
    def day_return(self) -> float:
        return self.equity / self.prev_equity - 1.0 if self.prev_equity else 0.0

    @property
    def total_return(self) -> float:
        return self.equity / self.starting_cash - 1.0 if self.starting_cash else 0.0


@dataclass(slots=True)
class Report:
    day: date
    bots: list[BotDay]  # best day return first
    trades: list[dict[str, Any]]
    flags: list[str]
    curves: dict[str, list[tuple[datetime, float]]]  # slug -> (ts, equity) over the day


def day_window(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time.min, ET)
    return start, datetime.combine(day + timedelta(days=1), time.min, ET)


def _evidence_text(ev: Any) -> str:
    if not isinstance(ev, list):
        return ""
    return "; ".join(f"{e.get('metric')}={e.get('value')}" for e in ev if isinstance(e, dict))


def build_report(conn: psycopg.Connection[dict[str, Any]], day: date) -> Report:
    start, end = day_window(day)
    bots = conn.execute("SELECT id, slug, name, starting_cash FROM bots ORDER BY id").fetchall()
    trades = conn.execute(
        """SELECT o.submitted_at, b.slug, b.name, o.symbol, o.side, o.qty, o.status, o.reject_reason,
                  o.broker, o.latency_ms, s.rationale, s.evidence,
                  (SELECT price FROM fills f WHERE f.order_id = o.id ORDER BY filled_at LIMIT 1) AS fill_price
           FROM orders o JOIN bots b ON b.id = o.bot_id JOIN signals s ON s.id = o.signal_id
           WHERE o.submitted_at >= %s AND o.submitted_at < %s ORDER BY o.submitted_at""",
        (start, end)).fetchall()
    for t in trades:
        t["evidence_text"] = _evidence_text(t["evidence"])
        t["time_et"] = t["submitted_at"].astimezone(ET).strftime("%Y-%m-%d %H:%M:%S")

    out: list[BotDay] = []
    curves: dict[str, list[tuple[datetime, float]]] = {}
    for b in bots:
        def equity_before(ts: datetime, bot_id: int = b["id"]) -> float | None:
            r = conn.execute("SELECT equity FROM equity_snapshots WHERE bot_id=%s AND ts < %s ORDER BY ts DESC LIMIT 1",
                             (bot_id, ts)).fetchone()
            return float(r["equity"]) if r else None

        cash0 = float(b["starting_cash"])
        end_eq = equity_before(end) or cash0
        prev_eq = equity_before(start) or cash0
        mine = [t for t in trades if t["slug"] == b["slug"]]
        pos = conn.execute("SELECT symbol, qty, avg_cost FROM positions WHERE bot_id=%s AND qty > 0 ORDER BY symbol",
                           (b["id"],)).fetchall()
        out.append(BotDay(
            slug=b["slug"], name=b["name"], equity=end_eq, prev_equity=prev_eq, starting_cash=cash0,
            trades=len(mine), filled=sum(t["status"] == "filled" for t in mine),
            rejected=sum(t["status"] == "rejected" for t in mine),
            positions=[(p["symbol"], float(p["qty"]), float(p["avg_cost"]),
                        db.latest_price(conn, p["symbol"]) or float(p["avg_cost"])) for p in pos]))
        curves[b["slug"]] = [(r["ts"], float(r["equity"])) for r in conn.execute(
            "SELECT ts, equity FROM equity_snapshots WHERE bot_id=%s AND ts >= %s AND ts < %s ORDER BY ts",
            (b["id"], start, end)).fetchall()]
    out.sort(key=lambda x: x.day_return, reverse=True)

    flags: list[str] = []
    for r in conn.execute(
            """SELECT b.name, o.symbol, o.side, o.submitted_at FROM orders o JOIN bots b ON b.id = o.bot_id
               WHERE o.status = 'submitted' AND o.submitted_at < now() - interval '10 minutes'
               ORDER BY o.submitted_at""").fetchall():
        flags.append(f"{r['name']}: {r['side']} {r['symbol']} stuck as 'submitted' since "
                     f"{r['submitted_at'].astimezone(ET):%b %d %H:%M} ET (no fill recorded).")
    for t in trades:
        if t["status"] == "rejected":
            flags.append(f"{t['name']}: {t['side']} {t['symbol']} rejected at {t['time_et'][11:16]} ET: {t['reject_reason']}")
    return Report(day, out, trades, flags[:12], curves)
