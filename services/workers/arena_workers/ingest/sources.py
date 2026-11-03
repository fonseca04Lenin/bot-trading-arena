"""Market-data sources: Alpaca (REST backfill + websocket) and a seeded synthetic walk for offline use."""

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timedelta

import httpx
import websockets

from ..common.config import Settings
from ..common.models import Bar
from ..common.universe import CRYPTO, EQUITIES, is_crypto

log = logging.getLogger("ingest")
OneMin = tuple[str, Bar]


def parse_alpaca_bar(raw: dict[str, object]) -> Bar:
    ts = datetime.fromisoformat(str(raw["t"]).replace("Z", "+00:00"))
    return Bar(ts, float(raw["o"]), float(raw["h"]), float(raw["l"]), float(raw["c"]),  # type: ignore[arg-type]
               float(raw.get("v", 0)))  # type: ignore[arg-type]


class AlpacaRest:
    def __init__(self, s: Settings) -> None:
        self.s = s
        self.headers = {"APCA-API-KEY-ID": s.alpaca_key, "APCA-API-SECRET-KEY": s.alpaca_secret}

    async def bars(self, symbol: str, timeframe: str, start: datetime, end: datetime | None = None) -> list[Bar]:
        crypto = is_crypto(symbol)
        url = f"{self.s.alpaca_data_url}/v1beta3/crypto/us/bars" if crypto else f"{self.s.alpaca_data_url}/v2/stocks/bars"
        params: dict[str, str | int] = {"symbols": symbol, "timeframe": timeframe, "start": start.isoformat(), "limit": 10000}
        if end:
            params["end"] = end.isoformat()
        if not crypto:
            params["feed"] = "iex"
        out: list[Bar] = []
        async with httpx.AsyncClient(timeout=30, headers=self.headers) as client:
            while True:
                r = await client.get(url, params=params)
                r.raise_for_status()
                body = r.json()
                out += [parse_alpaca_bar(b) for b in body["bars"].get(symbol, [])]
                if not body.get("next_page_token"):
                    return out
                params["page_token"] = body["next_page_token"]

    async def market_open(self) -> bool:
        async with httpx.AsyncClient(timeout=10, headers=self.headers) as client:
            r = await client.get(f"{self.s.alpaca_trading_url}/v2/clock")
            r.raise_for_status()
            return bool(r.json()["is_open"])


async def alpaca_stream(s: Settings, symbols: list[str]) -> AsyncIterator[OneMin]:
    """Yield 1-minute bars from the stock (IEX) and crypto websockets, reconnecting with backoff."""
    queue: asyncio.Queue[OneMin] = asyncio.Queue()

    async def pump(url: str, subs: list[str]) -> None:
        delay = 1.0
        while True:
            try:
                async with websockets.connect(url) as ws:
                    await ws.send(json.dumps({"action": "auth", "key": s.alpaca_key, "secret": s.alpaca_secret}))
                    await ws.send(json.dumps({"action": "subscribe", "bars": subs}))
                    delay = 1.0
                    async for msg in ws:
                        for item in json.loads(msg):
                            if item.get("T") == "b":
                                await queue.put((item["S"], parse_alpaca_bar(item)))
            except Exception as exc:  # reconnect on any transport error
                log.error("stream error %s; retrying in %.0fs", exc, delay)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)

    tasks = [
        asyncio.create_task(pump("wss://stream.data.alpaca.markets/v2/iex", [x for x in symbols if x in EQUITIES])),
        asyncio.create_task(pump("wss://stream.data.alpaca.markets/v1beta3/crypto/us", [x for x in symbols if x in CRYPTO])),
    ]
    try:
        while True:
            yield await queue.get()
    finally:
        for t in tasks:
            t.cancel()


class SyntheticWalk:
    """Deterministic-ish random walk so the whole stack runs without market-data keys."""

    BASE = {"SPY": 580.0, "QQQ": 500.0, "AAPL": 230.0, "MSFT": 420.0, "NVDA": 140.0, "AMZN": 200.0,
            "JPM": 240.0, "XOM": 115.0, "BTC/USD": 97000.0, "ETH/USD": 3400.0}

    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)
        self.price = dict(self.BASE)

    def next_bar(self, symbol: str, ts: datetime) -> Bar:
        vol = 0.0025 if is_crypto(symbol) else 0.0012
        o = self.price[symbol]
        c = o * (1 + self.rng.gauss(0, vol))
        h, l = max(o, c) * (1 + abs(self.rng.gauss(0, vol / 3))), min(o, c) * (1 - abs(self.rng.gauss(0, vol / 3)))
        self.price[symbol] = c
        return Bar(ts, o, h, l, c, float(self.rng.randint(1_000, 50_000)))

    def history(self, symbol: str, minutes: int, end: datetime) -> list[Bar]:
        start = end - timedelta(minutes=minutes)
        return [self.next_bar(symbol, start + timedelta(minutes=i)) for i in range(minutes)]


async def synthetic_stream(symbols: list[str], speed: float, walk: SyntheticWalk, clock: Callable[[], datetime],
                           sleep: Callable[[float], Awaitable[None]] = asyncio.sleep) -> AsyncIterator[OneMin]:
    """One synthetic 1-minute bar per symbol every `60/speed` seconds (speed 60 = one bar per second)."""
    t = clock().replace(second=0, microsecond=0)
    while True:
        t += timedelta(minutes=1)
        for sym in symbols:
            yield sym, walk.next_bar(sym, t)
        await sleep(60.0 / speed)
