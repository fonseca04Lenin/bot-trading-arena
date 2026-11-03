import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

_pool: AsyncConnectionPool | None = None


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://arena@localhost:5433/arena")


async def open_pool() -> AsyncConnectionPool:
    global _pool
    _pool = AsyncConnectionPool(database_url(), min_size=1, max_size=8, open=False,
                                kwargs={"row_factory": dict_row, "autocommit": True})
    await _pool.open()
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def conn() -> AsyncIterator[Any]:
    assert _pool is not None, "pool not open"
    async with _pool.connection() as c:
        yield c


async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
    async with conn() as c:
        cur = await c.execute(sql, args)
        return list(await cur.fetchall())


async def fetchone(sql: str, *args: Any) -> dict[str, Any] | None:
    rows = await fetch(sql, *args)
    return rows[0] if rows else None
