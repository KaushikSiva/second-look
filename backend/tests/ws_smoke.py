"""Smoke test the full live loop over the WebSocket with a typed question (no mic needed)."""
import asyncio
import json
import sys
import time

import websockets

PRODUCT = {"url": "https://www.amazon.com/dp/B07VVK39F7", "site": "amazon", "asin": "B07VVK39F7",
           "title": "LEVOIT Air Purifier for Home Bedroom, HEPA Filter Cleaner, Core 300", "brand": "LEVOIT",
           "price": 99.99, "list_price": 149.99, "rating": 4.7, "review_count": 120000, "model": "Core 300",
           "review_snippets": ["Works great, my allergies are better", "Received this free in exchange for an honest review. Love it!",
                               "Filter replacement is pricey", "Quiet on sleep mode"]}


async def main(q: str):
    async with websockets.connect("ws://localhost:8000/ws", max_size=None) as ws:
        await ws.send(json.dumps({"type": "page", "product": PRODUCT}))
        await ws.send(json.dumps({"type": "start"}))
        t0, sent, audio = time.time(), False, 0
        while time.time() - t0 < 90:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), 5))
            except asyncio.TimeoutError:
                continue
            if m["type"] == "status" and m["state"] == "live" and not sent:
                await ws.send(json.dumps({"type": "text", "text": q})); sent = True
            if m["type"] == "audio":
                audio += 1
                continue
            if m["type"] == "transcript" and m["role"] == "agent" and not m["final"]:
                print(m["text"], end="", flush=True)
                continue
            if m["type"] == "card":
                print(f"{time.time()-t0:5.1f}s CARD", m["card"]["kind"], json.dumps(m["card"])[:220])
            else:
                print(f"{time.time()-t0:5.1f}s", json.dumps(m)[:200])
            if m["type"] == "card" and m["card"]["kind"] == "verdict":
                t0 = time.time() - 75  # keep listening ~15s for the spoken summary
        print("audio chunks:", audio)

asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "Should I buy this?"))
