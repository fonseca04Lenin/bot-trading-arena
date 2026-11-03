from datetime import UTC, datetime

from ..common.models import Bar

FIVE = 300


def bucket_start(ts: datetime) -> datetime:
    epoch = int(ts.astimezone(UTC).timestamp())
    return datetime.fromtimestamp(epoch - epoch % FIVE, UTC)


class FiveMinAggregator:
    """Rolls 1-minute bars into 5-minute bars. A bucket closes when a bar from a later bucket arrives."""

    def __init__(self) -> None:
        self._open: dict[str, Bar] = {}

    def add(self, symbol: str, bar: Bar) -> Bar | None:
        start = bucket_start(bar.ts)
        cur = self._open.get(symbol)
        if cur is None or cur.ts == start:
            self._open[symbol] = self._merge(cur, start, bar)
            return None
        if start < cur.ts:
            return None
        self._open[symbol] = self._merge(None, start, bar)
        return cur

    @staticmethod
    def _merge(cur: Bar | None, start: datetime, bar: Bar) -> Bar:
        if cur is None:
            return Bar(start, bar.o, bar.h, bar.l, bar.c, bar.v)
        return Bar(start, cur.o, max(cur.h, bar.h), min(cur.l, bar.l), bar.c, cur.v + bar.v)
