"""WebSocket hub: relays Postgres NOTIFY events to subscribed clients."""

import asyncio
import json
import logging
from typing import Any

import psycopg
from fastapi import WebSocket, WebSocketDisconnect

from . import board, db

log = logging.getLogger("api.ws")
CHANNELS = {"trades", "equity", "ticker"}


class Hub:
    def __init__(self) -> None:
        self.clients: dict[WebSocket, set[str]] = {}

    async def broadcast(self, channel: str, event: dict[str, Any]) -> None:
        for ws, subs in list(self.clients.items()):
            if channel in subs:
                try:
                    await ws.send_json(event)
                except Exception:
                    self.clients.pop(ws, None)

    async def listen(self) -> None:
        """Dedicated LISTEN connection; reconnects on failure."""
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(db.database_url(), autocommit=True) as c:
                    for ch in ("trade_filled", "equity_tick", "bar_closed"):
                        await c.execute(f"LISTEN {ch}")
                    async for note in c.notifies():
                        await self.handle(note.channel, note.payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error("listen error: %s", exc)
                await asyncio.sleep(3)

    async def handle(self, channel: str, payload: str) -> None:
        if channel == "trade_filled":
            rows = await db.fetch(board.TRADE_SELECT + " WHERE o.id = %s", payload)
            if rows:
                await self.broadcast("trades", {"type": "trade_filled", "trade": board.trade_json(rows[0])})
        elif channel == "equity_tick":
            await self.broadcast("equity", {"type": "equity_tick", "ts": payload})
        elif channel == "bar_closed":
            symbol = payload.split("|")[0]
            row = await db.fetchone(
                "SELECT c FROM bars WHERE symbol=%s AND timeframe IN ('1Min','5Min') ORDER BY ts DESC LIMIT 1", symbol)
            if row:
                await self.broadcast("ticker", {"type": "price_tick", "symbol": symbol, "price": float(row["c"])})

    async def serve(self, ws: WebSocket) -> None:
        await ws.accept()
        self.clients[ws] = set()

        async def pinger() -> None:
            while True:
                await asyncio.sleep(20)
                await ws.send_json({"type": "ping"})

        ping = asyncio.create_task(pinger())
        try:
            while True:
                msg = json.loads(await ws.receive_text())
                if msg.get("action") == "subscribe":
                    self.clients[ws] |= set(msg.get("channels", [])) & CHANNELS
                    await ws.send_json({"type": "subscribed", "channels": sorted(self.clients[ws])})
        except (WebSocketDisconnect, ValueError):
            pass
        finally:
            ping.cancel()
            self.clients.pop(ws, None)
