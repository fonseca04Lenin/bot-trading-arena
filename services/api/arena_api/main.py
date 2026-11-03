import asyncio
import json
import logging
import os
import sys
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from arena_workers.analyst.version import PROMPT_VERSION
from arena_workers.common import db as wdb
from arena_workers.common.clock import equity_market_open, to_et
from arena_workers.common.headlines import Line, make_headline
from arena_workers.common.universe import CRYPTO, EQUITIES
from fastapi import FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import backtest, board, db
from .copy import GLOSSARY
from .ratelimit import RateLimiter
from .ws import Hub

log = logging.getLogger("api")
hub = Hub()
limiter = RateLimiter(10, 60.0)


async def _beat() -> None:
    while True:
        try:
            async with db.conn() as c:
                await c.execute("""INSERT INTO heartbeats (service,last_seen) VALUES ('api', now())
                    ON CONFLICT (service) DO UPDATE SET last_seen=now()""")
                await c.execute("INSERT INTO heartbeat_log (service, ts) VALUES ('api', now()) ON CONFLICT DO NOTHING")
        except Exception as exc:
            log.error("heartbeat failed: %s", exc)
        await asyncio.sleep(30)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    wdb.configure_logging("api")
    await db.open_pool()
    tasks = [asyncio.create_task(_beat()), asyncio.create_task(hub.listen())]
    yield
    for t in tasks:
        t.cancel()
    await db.close_pool()


app = FastAPI(title="Arena API", version="1.0.0", lifespan=lifespan)
origins = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:3000").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])


@app.middleware("http")
async def request_log(request: Request, call_next: Any) -> Response:
    rid = request.headers.get("x-request-id", uuid.uuid4().hex[:12])
    t0 = time.perf_counter()
    response: Response = await call_next(request)
    response.headers["x-request-id"] = rid
    sys.stdout.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "request_id": rid, "method": request.method,
                                 "path": request.url.path, "status": response.status_code,
                                 "ms": round((time.perf_counter() - t0) * 1000, 1)}) + "\n")
    return response


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    log.error("unhandled: %s", exc)
    return JSONResponse({"error": {"code": "internal", "message": "Something went wrong."}}, status_code=500)


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.status_code, "message": exc.detail}}, status_code=exc.status_code)


def cached(response: Response, seconds: int) -> None:
    response.headers["Cache-Control"] = f"public, max-age={seconds}"


async def freshness() -> dict[str, Any]:
    last = await board.last_bar_time()
    now = datetime.now(UTC)
    stale = last is None or (now - last).total_seconds() > 15 * 60
    return {"last_update": last.isoformat() if last else None, "stale": stale}


_slot_seen: dict[Any, int] = {}


async def current_headline(rows: list[dict[str, Any]]) -> dict[str, str]:
    """Regenerated from templates at the open, at noon and at the close (spec 11.4)."""
    et = to_et(datetime.now(UTC))
    slot = 0 if et.hour < 12 else 1 if et.hour < 16 else 2
    stored = await db.fetchone("SELECT headline, deck FROM headlines WHERE date=%s", et.date())
    if stored and _slot_seen.get(et.date()) == slot:
        return {"headline": stored["headline"], "deck": stored["deck"]}
    head, deck = make_headline([Line(r["slug"], r["name"], r["return"], r["today"]) for r in rows])
    await db.fetch("""INSERT INTO headlines (date, headline, deck) VALUES (%s,%s,%s) ON CONFLICT (date)
                      DO UPDATE SET headline=EXCLUDED.headline, deck=EXCLUDED.deck RETURNING date""",
                   et.date(), head, deck)
    _slot_seen[et.date()] = slot
    return {"headline": head, "deck": deck}


@app.get("/api/front-page")
async def front_page(response: Response) -> dict[str, Any]:
    cached(response, 5)
    rows = await board.leaderboard()
    launch = await db.fetchone("SELECT min(created_at) AS t FROM bots")
    day_no = (datetime.now(UTC) - launch["t"]).days + 1 if launch and launch["t"] else 1
    bots = await db.fetch("SELECT id, slug FROM bots")
    note = await db.fetchone("SELECT note FROM market_notes ORDER BY id DESC LIMIT 1")
    return {
        **await current_headline(rows),
        "edition_no": day_no,
        "market_open": equity_market_open(),
        "freshness": await freshness(),
        "leaderboard": rows,
        "trades": await board.trades(limit=12),
        "ticker": await board.ticker(),
        "equity": {b["slug"]: await board.equity_series(b["id"], "1W") for b in bots},
        "market_note": note["note"] if note else None,
    }


@app.get("/api/bots")
async def list_bots(response: Response) -> list[dict[str, Any]]:
    cached(response, 10)
    return await board.leaderboard()


@app.get("/api/bots/{slug}")
async def bot_detail(slug: str, response: Response) -> dict[str, Any]:
    cached(response, 10)
    bot = await db.fetchone("SELECT * FROM bots WHERE slug=%s", slug)
    if not bot:
        raise HTTPException(404, "No such bot.")
    pos = await db.fetch("SELECT symbol, qty, avg_cost FROM positions WHERE bot_id=%s AND qty > 0 ORDER BY symbol", bot["id"])
    positions = []
    for p in pos:
        px = await db.fetchone("SELECT c FROM bars WHERE symbol=%s AND timeframe IN ('1Min','5Min') ORDER BY ts DESC LIMIT 1", p["symbol"])
        last = float(px["c"]) if px else float(p["avg_cost"])
        positions.append({"symbol": p["symbol"], "qty": float(p["qty"]), "avg_cost": float(p["avg_cost"]),
                          "last": last, "pnl": (last - float(p["avg_cost"])) * float(p["qty"])})
    m = await board.bot_metrics(bot)
    out: dict[str, Any] = {**board.bot_row(bot), **m, "positions": positions}
    if slug == "analyst":
        out["prompt_version"] = PROMPT_VERSION
        out["eval"] = board.eval_report()
        out["budget"] = await board.agent_budget()
    return out


@app.get("/api/bots/{slug}/equity")
async def bot_equity(slug: str, response: Response, range: str = Query("1D", pattern="^(1D|1W|1M|ALL)$")) -> dict[str, Any]:
    cached(response, 10)
    bot = await db.fetchone("SELECT id FROM bots WHERE slug=%s", slug)
    if not bot:
        raise HTTPException(404, "No such bot.")
    pts = await board.equity_series(bot["id"], range)
    return {"slug": slug, "range": range, "points": [{"ts": t, "equity": e} for t, e in pts]}


@app.get("/api/trades")
async def list_trades(response: Response, bot: str | None = None, symbol: str | None = None,
                      before: datetime | None = None, limit: int = Query(20, ge=1, le=50)) -> dict[str, Any]:
    cached(response, 5)
    items = await board.trades(bot, symbol, before, limit)
    return {"items": items, "next_before": items[-1]["ts"] if len(items) == limit else None}


@app.get("/api/trades/{trade_id}")
async def trade_detail(trade_id: uuid.UUID) -> dict[str, Any]:
    rows = await db.fetch(board.TRADE_SELECT + " WHERE o.id=%s", trade_id)
    if not rows:
        raise HTTPException(404, "No such trade.")
    t = board.trade_json(rows[0])
    ts = rows[0]["ts"]
    bars = await db.fetch(
        """SELECT * FROM (SELECT ts,o,h,l,c FROM bars WHERE symbol=%s AND timeframe='5Min' AND ts <= %s
           ORDER BY ts DESC LIMIT 30) a UNION ALL
           SELECT * FROM (SELECT ts,o,h,l,c FROM bars WHERE symbol=%s AND timeframe='5Min' AND ts > %s
           ORDER BY ts LIMIT 12) b ORDER BY ts""", t["symbol"], ts, t["symbol"], ts)
    return {**t, "bars": [{"ts": b["ts"].isoformat(), "o": float(b["o"]), "h": float(b["h"]),
                           "l": float(b["l"]), "c": float(b["c"])} for b in bars]}


@app.post("/api/backtest")
async def post_backtest(req: backtest.BacktestRequest, request: Request) -> dict[str, Any]:
    ip = request.client.host if request.client else "unknown"
    if not limiter.allow(ip):
        raise HTTPException(429, "The Desk takes ten requests a minute. Try again shortly.")
    try:
        return await backtest.run(req)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except TimeoutError as exc:
        raise HTTPException(408, "That run took longer than 3 seconds.") from exc


@app.get("/api/status")
async def get_status(response: Response) -> dict[str, Any]:
    cached(response, 10)
    return {**await board.status(), "freshness": await freshness()}


@app.get("/api/glossary")
async def glossary(response: Response) -> list[dict[str, str]]:
    cached(response, 300)
    return GLOSSARY


@app.get("/api/universe")
async def universe() -> dict[str, list[str]]:
    return {"equities": list(EQUITIES), "crypto": list(CRYPTO)}


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await hub.serve(ws)
