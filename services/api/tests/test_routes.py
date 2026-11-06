import json
import time
import uuid

import psycopg
from fastapi.testclient import TestClient


def add_trade(c: psycopg.Connection, status: str = "filled") -> str:
    bot = c.execute("SELECT id FROM bots WHERE slug='breakout'").fetchone()
    sid, oid = uuid.uuid4(), uuid.uuid4()
    c.execute("INSERT INTO signals (id,bot_id,symbol,side,target_pct,rationale,evidence,bar_ts) "
              "VALUES (%s,%s,'AAPL','BUY',0.1,'Bought AAPL after a breakout.',%s,now())",
              (sid, bot["id"], json.dumps([{"metric": "HIGH20", "value": 1.5}])))
    c.execute("INSERT INTO orders (id,signal_id,bot_id,symbol,side,qty,idempotency_key,broker,status,reject_reason,latency_ms) "
              "VALUES (%s,%s,%s,'AAPL','BUY',5,%s,'sim','submitted',NULL,12)", (oid, sid, bot["id"], f"k{oid}"))
    if status == "filled":
        c.execute("INSERT INTO fills VALUES (%s,%s,5,100.02,now())", (uuid.uuid4(), oid))
    c.execute("UPDATE orders SET status=%s WHERE id=%s", (status, oid))
    return str(oid)


def test_front_page_has_all_bots_ranked(client: TestClient) -> None:
    r = client.get("/api/front-page")
    assert r.status_code == 200
    body = r.json()
    assert [x["rank"] for x in body["leaderboard"]] == [1, 2, 3, 4, 5, 6, 7]
    assert len(body["ticker"]) == 10 and body["headline"] and body["deck"]
    assert all(len(v) <= 300 for v in body["equity"].values())
    assert r.headers["cache-control"].startswith("public")


def test_bots_and_detail(client: TestClient) -> None:
    assert len(client.get("/api/bots").json()) == 7
    assert client.get("/api/bots/analyst").json()["rank"] in range(1, 8)
    d = client.get("/api/bots/analyst").json()
    assert d["slug"] == "analyst" and "prompt_version" not in d and "budget" not in d
    assert client.get("/api/bots/nobody").status_code == 404
    assert client.get("/api/bots/nobody").json()["error"]["code"] == 404


def test_equity_downsamples_to_300(client: TestClient) -> None:
    pts = client.get("/api/bots/index/equity?range=ALL").json()["points"]
    assert len(pts) == 300
    assert client.get("/api/bots/index/equity?range=bogus").status_code == 422


def test_trades_and_detail_include_scratched(client: TestClient, seeded: psycopg.Connection) -> None:
    ok, scratched = add_trade(seeded), add_trade(seeded, "rejected")
    items = client.get("/api/trades?limit=10").json()["items"]
    assert {i["id"] for i in items} == {ok, scratched}
    assert client.get("/api/trades?bot=index").json()["items"] == []
    d = client.get(f"/api/trades/{ok}").json()
    assert d["price"] == 100.02 and d["bars"] and d["evidence"][0]["metric"] == "HIGH20"
    assert client.get(f"/api/trades/{uuid.uuid4()}").status_code == 404


def test_backtest_and_validation_and_rate_limit(client: TestClient) -> None:
    from arena_api import main
    main.limiter.hits.clear()
    body = {"strategy_slug": "breakout", "symbol": "NVDA", "start": "2025-01-01T00:00:00Z", "end": "2026-06-01T00:00:00Z"}
    t0 = time.perf_counter()
    r = client.post("/api/backtest", json=body)
    assert r.status_code == 200 and time.perf_counter() - t0 < 3
    assert r.json()["metrics"]["bars"] > 100 and r.json()["equity"]
    assert client.post("/api/backtest", json={**body, "symbol": "ZZZZ"}).status_code == 422
    assert client.post("/api/backtest", json={**body, "strategy_slug": "analyst"}).status_code == 422
    assert client.post("/api/backtest", json={**body, "start": "2020-01-01T00:00:00Z"}).status_code == 422
    codes = [client.post("/api/backtest", json=body).status_code for _ in range(10)]
    assert codes[-1] == 429
    main.limiter.hits.clear()


def test_status_glossary_universe(client: TestClient, seeded: psycopg.Connection) -> None:
    time.sleep(0.5)
    s = client.get("/api/status").json()
    assert any(x["service"] == "api" for x in s["services"])
    assert "overall" in s["uptime"]
    assert len(client.get("/api/glossary").json()) >= 8
    assert "SPY" in client.get("/api/universe").json()["equities"]


def test_ws_delivers_trade_within_two_seconds(client: TestClient, seeded: psycopg.Connection) -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"action": "subscribe", "channels": ["trades"]})
        assert ws.receive_json()["type"] == "subscribed"
        time.sleep(0.5)  # let the LISTEN connection come up
        t0 = time.perf_counter()
        oid = add_trade(seeded)
        msg = ws.receive_json()
        assert msg["type"] == "trade_filled" and msg["trade"]["id"] == oid
        assert time.perf_counter() - t0 < 2
