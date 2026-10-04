"""Same product at other stores. Exa finds candidate listings fast; Kernel then opens the best one in a real cloud
browser and reads the live price, so a stale search snippet never becomes advice."""
import asyncio
import json

from . import llm
from .config import env, has, log

STORES = {"walmart.com": "Walmart", "bestbuy.com": "Best Buy", "target.com": "Target", "costco.com": "Costco"}

OFFERS_SCHEMA = {
    "type": "object",
    "properties": {"offers": {"type": "array", "items": {"type": "object", "properties": {
        "store": {"type": "string"}, "url": {"type": "string"}, "price": {"type": "number"},
        "same_product": {"type": "boolean", "description": "Exactly the same model/variant as the shopper's product"},
        "in_stock": {"type": "boolean", "description": "false if the page says out of stock / unavailable / sold out"},
        "note": {"type": "string"}}, "required": ["store", "url", "price", "same_product", "in_stock"]}}},
    "required": ["offers"],
}

# Runs inside Kernel's browser VM: read the live price from JSON-LD / meta / visible text.
LIVE_PRICE_JS = """
await page.goto(URL, { waitUntil: 'domcontentloaded', timeout: 25000 });
await page.waitForTimeout(2500);
return await page.evaluate(() => {
  const out = { title: document.title, price: null, in_stock: null };
  for (const s of document.querySelectorAll('script[type="application/ld+json"]')) {
    try {
      const walk = (o) => { if (!o || typeof o !== 'object') return;
        if (Array.isArray(o)) return o.forEach(walk);
        const offers = o.offers ? [].concat(o.offers) : [];
        for (const of of offers) { const p = parseFloat(of.price ?? of.lowPrice); if (p && !out.price) { out.price = p;
          out.in_stock = String(of.availability || '').includes('InStock'); } }
        Object.values(o).forEach(walk); };
      walk(JSON.parse(s.textContent));
    } catch (e) {}
  }
  if (!out.price) { const m = document.querySelector('meta[property="product:price:amount"], meta[itemprop="price"]');
    if (m) out.price = parseFloat(m.content); }
  if (!out.price) { const t = document.body.innerText.match(/\\$\\s?(\\d{1,4}(?:,\\d{3})*\\.\\d{2})/); if (t) out.price = parseFloat(t[1].replace(',', '')); }
  return out;
});
"""


async def live_price(url: str) -> dict | None:
    if not has("KERNEL_API_KEY"):
        return None
    from kernel import AsyncKernel
    k = AsyncKernel(api_key=env("KERNEL_API_KEY"))
    b = await k.browsers.create(stealth=True, headless=True, timeout_seconds=120)
    try:
        r = await k.browsers.playwright.execute(b.session_id, code=f"const URL = {json.dumps(url)};\n" + LIVE_PRICE_JS,
                                                timeout_sec=60)
        res = getattr(r, "result", None)
        if not isinstance(res, dict) or "not found" in (res.get("title") or "").lower():
            return None
        if not res.get("price") or float(res["price"]) < 5:  # JSON-LD junk like price: 1
            res["price"] = None
        return res
    finally:
        try:
            await k.browsers.delete_by_id(b.session_id)
        except Exception:  # noqa: BLE001
            pass


def _card(p: dict, offers: list[dict]) -> dict:
    cur = p.get("price") or 0
    offers = sorted(offers, key=lambda o: o["price"])
    for o in offers:
        if o.get("in_stock") is False:
            o["note"] = "out of stock"
    buyable = [o for o in offers if o.get("in_stock") is not False]
    best = None
    if buyable and cur and buyable[0]["price"] < cur - 0.5:
        best = {"store": buyable[0]["store"], "price": buyable[0]["price"], "saving": round(cur - buyable[0]["price"], 2),
                "url": buyable[0]["url"], "verified": buyable[0].get("verified", False)}
    rows = [{"store": "Amazon", "price": cur, "url": p.get("url"), "verified": True, "note": "you're here"}] + offers
    return {"id": "stores", "kind": "stores", "offers": rows, "best": best}


def _same_model(p: dict, title: str) -> bool:
    ident = (p.get("model") or "").lower().replace("-", " ")
    words = [w for w in ident.split() if len(w) > 1] or [w for w in (p.get("title") or "").lower().split()[:3]]
    t = (title or "").lower().replace("-", " ")
    return bool(words) and all(w in t for w in words) and "pack" not in t


async def compare(p: dict, emit, on_update=None) -> dict:
    """Fast path (Exa live crawl + Flash, ~5 s) returns the card the verdict uses. If Kernel is configured, a
    background pass then opens each store in a cloud browser and re-emits the card with live-verified prices,
    so a slow store page never holds up the conversation."""
    from .research import exa, short_title
    ident = p.get("model") or short_title(p)
    found = await exa().search(f"{p.get('brand') or ''} {ident}".strip(), num_results=8, include_domains=list(STORES), type="fast")
    urls = [x.url for x in found.results][:6]
    per_store: dict[str, str] = {}
    for u in urls:
        per_store.setdefault(u.split("/")[2].removeprefix("www."), u)

    results = []
    if urls:
        c = await exa().get_contents(urls, text={"max_characters": 3500}, livecrawl="always", livecrawl_timeout=6000)
        results = [{"url": x.url, "title": x.title, "text": x.text or ""} for x in c.results]
    srcs = "\n\n".join(f"[{r['url']}] {r['title']}\n{r['text'][:3000]}" for r in results)
    out = await llm.extract(
        f"Shopper's product: {p.get('title')} (model {p.get('model') or 'unknown'}) at ${p.get('price')} on Amazon.\n\n"
        f"Crawled listings:\n{srcs}\n\nReturn the current selling price of each listing that is the same product (ignore "
        f"prices of related/sponsored items, accessories and multi-packs). Store name from the domain "
        f"({', '.join(STORES.values())}). Mark different models/bundles as same_product=false.",
        OFFERS_SCHEMA) if results else {"offers": []}
    offers, seen = [], set()
    for o in sorted(out["offers"], key=lambda o: o.get("price") or 1e9):
        if o["same_product"] and o.get("price") and o["store"] not in seen:
            seen.add(o["store"])
            offers.append({**o, "verified": False})
    card = _card(p, offers)

    if has("KERNEL_API_KEY") and per_store:
        t = asyncio.create_task(_verify_live(p, offers, per_store, emit))
        _background.add(t)
        t.add_done_callback(_background.discard)
    return card


_background: set[asyncio.Task] = set()


async def _verify_live(p: dict, offers: list[dict], per_store: dict[str, str], emit):
    names = ", ".join(STORES.get(d, d) for d in per_store)
    await emit({"type": "tool", "id": "kernel", "name": "kernel", "state": "running", "label": f"Opening {names} in cloud browsers"})

    async def browse(url):
        try:
            return url, await asyncio.wait_for(live_price(url), 25)
        except Exception as e:  # noqa: BLE001
            log.warning("kernel %s: %r", url, e)
            return url, None

    reads = {u: r for u, r in await asyncio.gather(*[browse(u) for u in per_store.values()]) if r and r.get("price")}
    by_store = {o["store"]: o for o in offers}
    for u, r in reads.items():
        store = STORES.get(u.split("/")[2].removeprefix("www."))
        o = by_store.get(store)
        if o and (o["url"] == u or _same_model(p, r.get("title"))):
            o.update(price=float(r["price"]), verified=True, url=u)
            if r.get("in_stock") is not None:
                o["in_stock"] = r["in_stock"]
        elif not o and store and _same_model(p, r.get("title")):
            by_store[store] = {"store": store, "url": u, "price": float(r["price"]), "same_product": True,
                               "in_stock": r.get("in_stock"), "verified": True, "note": r.get("title", "")[:60]}
    await emit({"type": "tool", "id": "kernel", "name": "kernel", "state": "done" if reads else "error",
                "label": f"Verified {len(reads)} live price{'s' if len(reads) != 1 else ''} in Kernel" if reads else "Live check blocked"})
    if reads:
        await emit({"type": "card", "card": _card(p, list(by_store.values()))})
