from datetime import UTC, datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
_OPEN, _CLOSE = time(9, 30), time(16, 0)


def to_et(ts: datetime) -> datetime:
    return ts.astimezone(ET)


def equity_market_open(now: datetime | None = None) -> bool:
    """Weekday 9:30-16:00 ET. Holidays are caught by the live Alpaca clock check in ingest."""
    et = to_et(now or datetime.now(UTC))
    return et.weekday() < 5 and _OPEN <= et.time() < _CLOSE
