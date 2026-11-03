from datetime import UTC, datetime

from arena_workers.common.models import Bar
from arena_workers.ingest.aggregate import FiveMinAggregator, bucket_start


def b(minute: int, o: float, h: float, l: float, c: float, v: float = 10) -> Bar:
    return Bar(datetime(2026, 1, 5, 14, minute, tzinfo=UTC), o, h, l, c, v)


def test_bucket_start() -> None:
    assert bucket_start(datetime(2026, 1, 5, 14, 7, 30, tzinfo=UTC)).minute == 5


def test_aggregates_five_one_minute_bars() -> None:
    agg = FiveMinAggregator()
    for m, (o, h, l, c) in enumerate([(1, 2, 0.5, 1.5), (1.5, 3, 1, 2), (2, 2.5, 1.8, 2.2),
                                      (2.2, 2.4, 2, 2.1), (2.1, 2.6, 1.9, 2.5)]):
        assert agg.add("X", b(m, o, h, l, c)) is None
    closed = agg.add("X", b(5, 2.5, 2.7, 2.4, 2.6))
    assert closed is not None
    assert (closed.o, closed.h, closed.l, closed.c, closed.v) == (1, 3, 0.5, 2.5, 50)
    assert closed.ts.minute == 0


def test_symbols_are_independent_and_late_bars_ignored() -> None:
    agg = FiveMinAggregator()
    agg.add("A", b(5, 1, 1, 1, 1))
    assert agg.add("B", b(0, 1, 1, 1, 1)) is None
    assert agg.add("A", b(0, 9, 9, 9, 9)) is None
