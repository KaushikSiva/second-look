import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from . import db, mail, research
from .config import has, log
from .live import Bridge


class Hub:
    """Every open side panel, so inbox events and price alerts reach the shopper live."""

    def __init__(self):
        self.bridges: set[Bridge] = set()

    async def broadcast(self, msg: dict):
        for b in list(self.bridges):
            await b.emit(msg)


hub = Hub()


async def check_watchlist():
    """Re-check watched products' prices (Kernel live page read when available) and email on a drop."""
    from .stores import live_price
    while True:
        await asyncio.sleep(60 * 60 * 3)
        try:
            for w in await db.q("select * from watchlist where triggered_at is null"):
                live = await live_price(w["url"]) if has("KERNEL_API_KEY") else None
                if live and live.get("price"):
                    await price_drop(w, float(live["price"]), source="kernel")
        except Exception as e:  # noqa: BLE001
            log.warning("watchlist: %r", e)


async def price_drop(w: dict, new_price: float, source: str = "observed"):
    await db.q("insert into price_history (product_key, price, source) values (%s,%s,%s)", w["product_key"], new_price, source)
    if new_price > float(w["target_price"]):
        return {"triggered": False, "price": new_price}
    await db.q("update watchlist set triggered_at=now(), current_price=%s where id=%s", new_price, w["id"])
    saved = int(round((float(w["current_price"] or new_price) - new_price) * 100))
    total = await db.add_saving("price_drop", max(saved, 0), f"Price drop on {w['title']}")
    body = (f"Good news — \"{w['title']}\" just dropped to ${new_price:.2f} (your target was ${float(w['target_price']):.2f}).\n\n"
            f"{w['url']}\n\n— Second Look")
    card = await mail.alert_user(f"Price drop: now ${new_price:.2f}", body)
    await hub.broadcast({"type": "card", "card": card or {"id": f"drop-{w['id']}", "kind": "email", "to": "you",
                                                          "subject": f"Price drop: now ${new_price:.2f}", "body": body, "status": "draft"}})
    await hub.broadcast({"type": "savings", "total_cents": total})
    return {"triggered": True, "price": new_price}


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    tasks = [asyncio.create_task(check_watchlist())]
    if has("AGENTMAIL_API_KEY"):
        tasks.append(asyncio.create_task(mail.poll(hub.broadcast)))
    yield
    for t in tasks:
        t.cancel()


app = FastAPI(title="Second Look", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
async def health():
    return {"ok": True, "inbox": await mail.inbox_id(),
            "integrations": {k: has(v) for k, v in {"gemini": "GEMINI_API_KEY", "jev": "TYPESAFE_API_KEY", "exa": "EXA_API_KEY",
                                                     "kernel": "KERNEL_API_KEY", "agentmail": "AGENTMAIL_API_KEY",
                                                     "neon": "DATABASE_URL"}.items()}}


@app.get("/api/watchlist")
async def watchlist():
    return await db.q("select * from watchlist order by id desc")


@app.get("/api/savings")
async def savings():
    return {"total_cents": await db.total_savings(), "items": await db.q("select * from savings order by id desc limit 50")}


@app.post("/api/watch/{watch_id}/check")
async def check_now(watch_id: int, price: float | None = None):
    """Run a watch check now. `price` overrides the live read — used to trigger a drop on stage."""
    w = (await db.q("select * from watchlist where id=%s", watch_id) or [None])[0]
    if not w:
        return {"error": "not found"}
    if price is None:
        from .stores import live_price
        live = await live_price(w["url"])
        price = live and live.get("price")
        if not price:
            return {"error": "could not read live price"}
    return await price_drop(w, float(price), source="manual" if price else "kernel")


@app.post("/api/research")
async def research_http(product: dict):
    """Same research pipeline without voice (handy for testing and the text-only fallback)."""
    cards = []

    async def emit(m):
        cards.append(m)
    summary = await research.research_product(product, emit)
    return {"summary": summary, "events": cards}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    bridge = Bridge(ws, hub)
    hub.bridges.add(bridge)
    try:
        while True:
            m = json.loads(await ws.receive_text())
            if m.get("type") == "page":
                await bridge.set_product(m.get("product"))
            elif m.get("type") == "start":
                try:
                    await bridge.run()
                except WebSocketDisconnect:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.exception("live session failed")
                    await bridge.emit({"type": "status", "state": "error", "message": str(e)[:200]})
                await bridge.emit({"type": "status", "state": "closed"})
    except WebSocketDisconnect:
        pass
    finally:
        hub.bridges.discard(bridge)
        for t in list(bridge.tasks):
            t.cancel()
