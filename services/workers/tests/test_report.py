from datetime import UTC, date, datetime
from typing import Any

import pytest

from arena_workers.report import daily
from arena_workers.report.data import BotDay, Report
from arena_workers.report.render import build_pdf, email_html, headline, standings_csv, trades_csv


def _report(flat: bool = False) -> Report:
    t = datetime(2026, 11, 6, 14, 36, tzinfo=UTC)
    bots = [BotDay("index", "The Index", 100_558.0, 100_000.0, 100_000.0, trades=1, filled=1,
                   positions=[("SPY", 135.9, 735.4, 740.0)]),
            BotDay("quant", "The Quant", 100_000.0, 100_000.0, 100_000.0)]
    if flat:
        bots[0] = BotDay("index", "The Index", 100_000.0, 100_000.0, 100_000.0)
    trade = {"submitted_at": t, "time_et": "2026-11-06 09:36:00", "slug": "index", "name": "The Index",
             "symbol": "SPY", "side": "BUY", "qty": 135.9772, "status": "filled", "reject_reason": None,
             "broker": "sim", "latency_ms": 338, "rationale": "Bought SPY — the benchmark †",
             "evidence": [], "evidence_text": "S_SCORE=-3.7; BETA=1.4", "fill_price": 735.42}
    curves = {"index": [(t, 100_000.0), (t.replace(minute=41), 100_300.0)],
              "quant": [(t, 100_000.0), (t.replace(minute=41), 100_000.0)]}
    return Report(date(2026, 11, 6), bots, [trade] if not flat else [], ["Crossover: NVDA stuck"], curves)


def test_headline_names_the_best_bot() -> None:
    assert "The Index did best today (+0.56%)" in headline(_report())
    assert headline(_report(flat=True)).startswith("Quiet day")


def test_csvs_have_one_row_per_trade_and_per_bot() -> None:
    r = _report()
    t = trades_csv(r).strip().splitlines()
    assert len(t) == 2 and "index,SPY,BUY,135.9772,735.42,100000.35" in t[1]
    s = standings_csv(r).strip().splitlines()
    assert len(s) == 3 and s[1].startswith("2026-11-06,1,index,100558.0")


def test_pdf_renders_with_non_latin_text_and_empty_days() -> None:
    assert build_pdf(_report()).startswith(b"%PDF")
    assert build_pdf(_report(flat=True)).startswith(b"%PDF")


def test_email_html_highlights_winner_and_flags() -> None:
    html = email_html(_report())
    assert "The Index did best today" in html and "NVDA stuck" in html


class _Conn:
    def __init__(self, claimed: bool = True) -> None:
        self.claimed = claimed
        self.sql: list[str] = []

    def execute(self, sql: str, *a: Any) -> "_Conn":
        self.sql.append(sql.split()[0])
        return self

    def fetchone(self) -> dict[str, Any] | None:
        return {"day": 1} if self.claimed else None


@pytest.fixture(autouse=True)
def _reset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(daily, "_started", False)
    monkeypatch.setattr(daily, "_table_ready", False)
    for k in ("RESEND_API_KEY", "REPORT_EMAIL_TO", "REPORT_SEND_ON_START"):
        monkeypatch.delenv(k, raising=False)


def _configured(monkeypatch: pytest.MonkeyPatch, sent: list[date]) -> None:
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("REPORT_EMAIL_TO", "me@example.com")
    monkeypatch.setattr(daily, "send_report", lambda conn, day: sent.append(day))


def test_does_nothing_without_credentials() -> None:
    assert daily.maybe_send_daily(_Conn(), datetime(2026, 11, 6, 22, 0, tzinfo=UTC)) is False  # type: ignore[arg-type]


def test_sends_once_after_the_close_on_weekdays(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[date] = []
    _configured(monkeypatch, sent)
    friday_after = datetime(2026, 11, 6, 21, 30, tzinfo=UTC)  # 16:30 ET
    assert daily.maybe_send_daily(_Conn(), friday_after) is True  # type: ignore[arg-type]
    assert sent == [date(2026, 11, 6)]
    assert daily.maybe_send_daily(_Conn(claimed=False), friday_after) is False  # type: ignore[arg-type]
    assert len(sent) == 1


def test_waits_for_the_close_and_skips_weekends(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[date] = []
    _configured(monkeypatch, sent)
    assert daily.maybe_send_daily(_Conn(), datetime(2026, 11, 6, 20, 0, tzinfo=UTC)) is False  # type: ignore[arg-type]  # 15:00 ET
    assert daily.maybe_send_daily(_Conn(), datetime(2026, 11, 7, 21, 30, tzinfo=UTC)) is False  # type: ignore[arg-type]  # Saturday
    assert sent == []


def test_a_failed_send_is_swallowed_and_released_for_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    _configured(monkeypatch, [])

    def boom(conn: Any, day: date) -> None:
        raise RuntimeError("resend down")

    monkeypatch.setattr(daily, "send_report", boom)
    c = _Conn()
    assert daily.maybe_send_daily(c, datetime(2026, 11, 6, 21, 30, tzinfo=UTC)) is False  # type: ignore[arg-type]
    assert "DELETE" in c.sql


def test_build_report_from_the_database(conn: Any) -> None:
    import uuid

    from arena_workers.common import db
    from arena_workers.report.data import build_report

    db.seed_bots(conn)
    ids = {r["slug"]: r["id"] for r in conn.execute("SELECT id, slug FROM bots").fetchall()}
    when = datetime(2026, 11, 6, 14, 36, tzinfo=UTC)  # 09:36 ET

    def trade(slug: str, status: str, price: float | None) -> None:
        sid, oid = uuid.uuid4(), uuid.uuid4()
        conn.execute("INSERT INTO signals (id, bot_id, symbol, side, target_pct, rationale, evidence, bar_ts) "
                     "VALUES (%s,%s,'SPY','BUY',1,'Bought SPY','[{\"metric\":\"X\",\"value\":1}]',%s)", (sid, ids[slug], when))
        conn.execute("INSERT INTO orders (id, signal_id, bot_id, symbol, side, qty, idempotency_key, broker, status, submitted_at) "
                     "VALUES (%s,%s,%s,'SPY','BUY',10,%s,'sim',%s,%s)", (oid, sid, ids[slug], f"k-{sid}", status, when))
        if price is not None:
            conn.execute("INSERT INTO fills (id, order_id, qty, price) VALUES (%s,%s,10,%s)", (uuid.uuid4(), oid, price))

    trade("index", "filled", 735.42)
    trade("crossover", "submitted", None)  # never filled: should be flagged
    for slug, prev, end in (("index", 100_000, 100_558), ("crossover", 100_000, 100_000)):
        conn.execute("INSERT INTO equity_snapshots VALUES (%s,%s,%s)", (ids[slug], datetime(2026, 11, 5, 21, 0, tzinfo=UTC), prev))
        conn.execute("INSERT INTO equity_snapshots VALUES (%s,%s,%s)", (ids[slug], datetime(2026, 11, 6, 15, 0, tzinfo=UTC), prev))
        conn.execute("INSERT INTO equity_snapshots VALUES (%s,%s,%s)", (ids[slug], datetime(2026, 11, 6, 21, 0, tzinfo=UTC), end))
    conn.execute("INSERT INTO positions VALUES (%s,'SPY',10,735.42)", (ids["index"],))

    rep = build_report(conn, date(2026, 11, 6))
    assert rep.bots[0].slug == "index" and round(rep.bots[0].day_return, 4) == 0.0056
    assert rep.bots[0].trades == 1 and rep.bots[0].filled == 1 and rep.bots[0].positions[0][0] == "SPY"
    assert float(next(t for t in rep.trades if t["slug"] == "index")["fill_price"]) == 735.42
    assert any("The Crossover" in f and "stuck" in f for f in rep.flags)
    assert len(rep.curves["index"]) == 2 and rep.trades[0]["time_et"].startswith("2026-11-06 09:36")
    assert "The Index did best today" in headline(rep)
    assert build_pdf(rep).startswith(b"%PDF")
    assert build_report(conn, date(2026, 11, 7)).trades == []
