"""Turn a Report into CSV files, an HTML email body and a PDF. Pure formatting, no I/O."""

import csv
import io
from datetime import datetime

from fpdf import FPDF

from ..common.clock import ET
from .data import BotDay, Report

INK = {"index": (47, 138, 87), "analyst": (122, 63, 176), "crossover": (226, 85, 45),
       "breakout": (43, 95, 199), "rubber-band": (232, 169, 33), "quant": (31, 157, 157)}


def pct(x: float) -> str:
    return f"{x * 100:+.2f}%"


def money(x: float) -> str:
    return f"${x:,.2f}"


def _latin(s: object) -> str:
    """fpdf's built-in fonts are latin-1 only."""
    t = str(s).replace("—", "-").replace("–", "-").replace("’", "'").replace("‘", "'")
    t = t.replace("“", '"').replace("”", '"').replace("†", "*")
    return t.encode("latin-1", "replace").decode("latin-1")


def headline(r: Report) -> str:
    best = r.bots[0]
    if all(abs(b.day_return) < 1e-9 for b in r.bots):
        return "Quiet day: no bot moved."
    top_total = max(r.bots, key=lambda b: b.total_return)
    s = f"{best.name} did best today ({pct(best.day_return)})."
    if top_total.slug != best.slug:
        s += f" {top_total.name} still leads since launch ({pct(top_total.total_return)})."
    return s


def trades_csv(r: Report) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["time_et", "bot", "symbol", "side", "qty", "fill_price", "notional", "broker", "status",
                "reject_reason", "latency_ms", "reason", "evidence"])
    for t in r.trades:
        fp = float(t["fill_price"]) if t["fill_price"] is not None else None
        w.writerow([t["time_et"], t["slug"], t["symbol"], t["side"], float(t["qty"]), fp,
                    round(fp * float(t["qty"]), 2) if fp is not None else "", t["broker"], t["status"],
                    t["reject_reason"] or "", t["latency_ms"] if t["latency_ms"] is not None else "",
                    t["rationale"], t["evidence_text"]])
    return buf.getvalue()


def standings_csv(r: Report) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["date", "rank_today", "bot", "equity", "prev_equity", "day_return", "total_return", "trades",
                "filled", "rejected", "open_positions"])
    for i, b in enumerate(r.bots, 1):
        w.writerow([r.day.isoformat(), i, b.slug, round(b.equity, 2), round(b.prev_equity, 2),
                    round(b.day_return, 6), round(b.total_return, 6), b.trades, b.filled, b.rejected,
                    " ".join(p[0] for p in b.positions)])
    return buf.getvalue()


def email_html(r: Report) -> str:
    rows = "".join(
        f"<tr><td>{i}</td><td><b>{b.name}</b></td><td align=right>{money(b.equity)}</td>"
        f"<td align=right>{pct(b.day_return)}</td><td align=right>{pct(b.total_return)}</td>"
        f"<td align=right>{b.trades}</td></tr>" for i, b in enumerate(r.bots, 1))
    flags = "".join(f"<li>{f}</li>" for f in r.flags) or "<li>None.</li>"
    return (f"<div style='font-family:Georgia,serif;max-width:640px'><h2>The Arena Daily: {r.day:%A %b %d, %Y}</h2>"
            f"<p style='font-size:16px'><b>{headline(r)}</b></p>"
            "<table cellpadding=6 style='border-collapse:collapse;font-size:14px' border=0>"
            "<tr style='border-bottom:1px solid #999'><th>#</th><th align=left>Bot</th><th>Equity</th><th>Today</th>"
            f"<th>Since launch</th><th>Trades</th></tr>{rows}</table>"
            f"<h3>Flags</h3><ul>{flags}</ul>"
            "<p style='color:#666'>Full trade log attached as PDF, plus CSV files for analysis.</p></div>")


class _Pdf(FPDF):
    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120)
        self.cell(0, 6, f"Private report - page {self.page_no()}", align="C")


def _chart(pdf: _Pdf, r: Report, x: float, y: float, w: float, h: float) -> None:
    pdf.set_draw_color(200)
    pdf.rect(x, y, w, h)
    series = {s: c for s, c in r.curves.items() if len(c) >= 2}
    if not series:
        pdf.set_xy(x, y + h / 2 - 3)
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(w, 6, "No equity snapshots for this day.", align="C")
        return
    base = {s: c[0][1] for s, c in series.items()}
    pcts = {s: [(t, v / base[s] - 1) for t, v in c] for s, c in series.items()}
    lo = min(p for c in pcts.values() for _, p in c)
    hi = max(p for c in pcts.values() for _, p in c)
    span = (hi - lo) or 1e-9
    t0 = min(c[0][0] for c in pcts.values())
    t1 = max(c[-1][0] for c in pcts.values())
    tspan = (t1 - t0).total_seconds() or 1.0
    for s, c in pcts.items():
        pdf.set_draw_color(*INK.get(s, (60, 60, 60)))
        pdf.set_line_width(0.5)
        pts = [(x + (t - t0).total_seconds() / tspan * w, y + h - (p - lo) / span * h) for t, p in c]
        for a, b in zip(pts, pts[1:], strict=False):
            pdf.line(a[0], a[1], b[0], b[1])
    pdf.set_line_width(0.2)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(100)
    pdf.text(x + 1, y + 4, pct(hi))
    pdf.text(x + 1, y + h - 1.5, pct(lo))
    pdf.set_text_color(0)


def build_pdf(r: Report) -> bytes:
    pdf = _Pdf(orientation="P", unit="mm", format="Letter")
    pdf.set_auto_page_break(True, 16)
    pdf.add_page()
    pdf.set_font("Times", "B", 20)
    pdf.cell(0, 10, "THE ARENA DAILY - TRADE LOG", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.cell(0, 6, f"{r.day:%A, %B %d, %Y}   (times in US Eastern)", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 12)
    pdf.multi_cell(0, 7, _latin(headline(r)), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    cols = [("#", 8), ("Bot", 50), ("Equity", 30), ("Today", 22), ("Launch", 22), ("Trades", 18), ("Fill/Rej", 22)]
    pdf.set_font("Helvetica", "B", 9)
    for name, wd in cols:
        pdf.cell(wd, 7, name, border="B")
    pdf.ln()
    pdf.set_font("Helvetica", "", 9)
    for i, b in enumerate(r.bots, 1):
        vals = [str(i), b.name, money(b.equity), pct(b.day_return), pct(b.total_return), str(b.trades),
                f"{b.filled}/{b.rejected}"]
        for v, (_, wd) in zip(vals, cols, strict=True):
            pdf.cell(wd, 6.5, _latin(v))
        pdf.ln()
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Equity today (% change from first snapshot)", new_x="LMARGIN", new_y="NEXT")
    cy = pdf.get_y()
    _chart(pdf, r, 10, cy, 190, 50)
    pdf.set_y(cy + 52)
    pdf.set_font("Helvetica", "", 8)
    for b in r.bots:
        pdf.set_text_color(*INK.get(b.slug, (60, 60, 60)))
        pdf.cell(32, 5, _latin(f"- {b.name}"))
    pdf.set_text_color(0)
    pdf.ln(9)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, "Flags", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    for f in r.flags or ["None."]:
        pdf.multi_cell(0, 5, _latin("- " + f), new_x="LMARGIN", new_y="NEXT")
    for b in sorted(r.bots, key=lambda x: x.name):
        _bot_section(pdf, r, b)
    return bytes(pdf.output())


def _bot_section(pdf: _Pdf, r: Report, b: BotDay) -> None:
    pdf.add_page()
    pdf.set_font("Times", "B", 16)
    pdf.set_text_color(*INK.get(b.slug, (0, 0, 0)))
    pdf.cell(0, 9, _latin(b.name.upper()), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 5, _latin(f"Equity {money(b.equity)}   Today {pct(b.day_return)}   Since launch {pct(b.total_return)}"
                          f"   Trades {b.trades} (filled {b.filled}, rejected {b.rejected})"),
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    mine = [t for t in r.trades if t["slug"] == b.slug]
    if not mine:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, "No trades today.", new_x="LMARGIN", new_y="NEXT")
    for t in mine:
        fp = f"{float(t['fill_price']):,.2f}" if t["fill_price"] is not None else "no fill"
        pdf.set_font("Helvetica", "B", 9)
        head = f"{t['time_et'][11:16]}  {t['side']}  {t['symbol']}  {float(t['qty']):,.4f} @ {fp}  [{t['status']}]"
        pdf.multi_cell(0, 5, _latin(head), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 8.5)
        pdf.multi_cell(0, 4.5, _latin(t["rationale"]), new_x="LMARGIN", new_y="NEXT")
        if t["evidence_text"]:
            pdf.set_text_color(110)
            pdf.multi_cell(0, 4.5, _latin(t["evidence_text"]), new_x="LMARGIN", new_y="NEXT")
            pdf.set_text_color(0)
        pdf.ln(1.5)
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "Open positions", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    if not b.positions:
        pdf.cell(0, 5, "None.", new_x="LMARGIN", new_y="NEXT")
    for sym, qty, cost, last in b.positions:
        gain = last / cost - 1 if cost else 0.0
        pdf.cell(0, 5, _latin(f"{sym}: {qty:,.4f} @ avg {cost:,.2f}, last {last:,.2f} ({pct(gain)})"),
                 new_x="LMARGIN", new_y="NEXT")


def stamp(now: datetime) -> str:
    return now.astimezone(ET).strftime("%Y-%m-%d")


def attachments(r: Report) -> list[tuple[str, bytes]]:
    d = r.day.isoformat()
    return [(f"arena-report-{d}.pdf", build_pdf(r)), (f"trades-{d}.csv", trades_csv(r).encode()),
            (f"standings-{d}.csv", standings_csv(r).encode())]
