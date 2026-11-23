"""A service that cannot reach the database must wait and try again, not exit (see db.keep_running)."""

import logging

import psycopg
import pytest

from arena_workers.common import db

LOG = logging.getLogger("test")


class Clock:
    """A fake clock: `sleep` advances time and records how long it was asked to wait."""

    def __init__(self) -> None:
        self.now: float = 0.0
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def monotonic(self) -> float:
        return self.now


def test_runs_again_after_the_database_cannot_be_reached() -> None:
    clock, attempts = Clock(), []

    def serve() -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise psycopg.OperationalError("connection failed: Network is unreachable")

    db.keep_running(LOG, serve, sleep=clock.sleep, monotonic=clock.monotonic)
    assert len(attempts) == 3 and clock.sleeps == [5.0, 10.0]  # it waited, and waited longer the second time


def test_waits_no_longer_than_a_minute_between_attempts() -> None:
    clock, attempts = Clock(), []

    def serve() -> None:
        attempts.append(1)
        if len(attempts) < 9:
            raise psycopg.OperationalError("down")

    db.keep_running(LOG, serve, sleep=clock.sleep, monotonic=clock.monotonic)
    assert clock.sleeps == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0, 60.0, 60.0]


def test_a_dropped_connection_after_a_long_healthy_run_starts_the_wait_over() -> None:
    clock, attempts = Clock(), []

    def serve() -> None:
        attempts.append(1)
        if len(attempts) in (1, 2):
            raise psycopg.OperationalError("down")
        if len(attempts) == 3:
            clock.now += 600  # it ran fine for ten minutes, then the connection dropped
            raise psycopg.InterfaceError("connection already closed")

    db.keep_running(LOG, serve, sleep=clock.sleep, monotonic=clock.monotonic)
    assert clock.sleeps == [5.0, 10.0, 5.0]


def test_other_errors_are_bugs_and_still_stop_the_service() -> None:
    clock = Clock()

    def serve() -> None:
        raise ValueError("a real bug")

    with pytest.raises(ValueError):
        db.keep_running(LOG, serve, sleep=clock.sleep, monotonic=clock.monotonic)
    assert clock.sleeps == []


def test_connect_gives_up_on_an_unreachable_host_quickly(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}

    def fake_connect(url: str, **kwargs: object) -> object:
        seen.update(kwargs)
        return object()

    monkeypatch.setattr(db.psycopg, "connect", fake_connect)
    db.connect()
    assert seen["connect_timeout"] == db.CONNECT_TIMEOUT == 10


def test_the_service_entry_points_are_wrapped_in_the_retry() -> None:
    import inspect

    from arena_workers.ingest import main as ingest
    from arena_workers.strategies import main as strategies

    assert "keep_running" in inspect.getsource(ingest.run)
    assert "keep_running" in inspect.getsource(strategies.main)
