"""Email a private trade report once each weekday after the close.

Configured by environment variables on the service that runs it (the scorer):
  RESEND_API_KEY      API key from resend.com (required; without it nothing is sent)
  REPORT_EMAIL_TO     where to send it (required)
  REPORT_EMAIL_FROM   optional; defaults to Resend's shared sender, which can only deliver to the account owner
  REPORT_SEND_ON_START=1   optional; sends today's report once on startup to test the setup
Nothing here is served over HTTP: the data leaves only as the email.
"""

import base64
import logging
import os
from datetime import UTC, date, datetime, time
from typing import Any

import httpx
import psycopg

from ..common.clock import to_et
from .data import build_report
from .render import attachments, email_html, headline

log = logging.getLogger("report")
SEND_AFTER = time(16, 15)  # ET, 15 minutes after the close
_started = False
_table_ready = False


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def send_email(subject: str, html: str, files: list[tuple[str, bytes]]) -> None:
    resp = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {_env('RESEND_API_KEY')}"},
        json={"from": _env("REPORT_EMAIL_FROM") or "Arena Reports <onboarding@resend.dev>",
              "to": [_env("REPORT_EMAIL_TO")], "subject": subject, "html": html,
              "attachments": [{"filename": n, "content": base64.b64encode(b).decode()} for n, b in files]},
        timeout=30)
    resp.raise_for_status()


def send_report(conn: psycopg.Connection[dict[str, Any]], day: date) -> None:
    r = build_report(conn, day)
    send_email(f"Arena report {day:%a %b %d}: {headline(r)}", email_html(r), attachments(r))


def _ensure_table(conn: psycopg.Connection[dict[str, Any]]) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS report_log (day DATE PRIMARY KEY, sent_at TIMESTAMPTZ NOT NULL DEFAULT now())")


def maybe_send_daily(conn: psycopg.Connection[dict[str, Any]], now: datetime | None = None) -> bool:
    """Called on every scorer tick. Never raises: a broken report must not stop the scorer."""
    global _started, _table_ready
    try:
        if not (_env("RESEND_API_KEY") and _env("REPORT_EMAIL_TO")):
            return False
        et = to_et(now or datetime.now(UTC))
        if not _started:
            _started = True
            if _env("REPORT_SEND_ON_START") in ("1", "true", "yes"):
                send_report(conn, et.date())
                log.info("test report sent for %s", et.date())
        if et.weekday() >= 5 or et.time() < SEND_AFTER:
            return False
        if not _table_ready:
            _ensure_table(conn)
            _table_ready = True
        # Claim the day first so two instances or a restart cannot send it twice.
        claimed = conn.execute("INSERT INTO report_log (day) VALUES (%s) ON CONFLICT DO NOTHING RETURNING day",
                               (et.date(),)).fetchone()
        if claimed is None:
            return False
        try:
            send_report(conn, et.date())
        except Exception:
            conn.execute("DELETE FROM report_log WHERE day = %s", (et.date(),))  # let the next tick retry
            raise
        log.info("daily report sent for %s", et.date())
        return True
    except Exception as exc:  # noqa: BLE001
        log.error("daily report failed: %s", type(exc).__name__)  # no details: they could include the API key
        return False

