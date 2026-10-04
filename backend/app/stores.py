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
        "note": {"type": "string"}}, "required": ["store", "url", "price", "same_product"]}}},
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
        return res if isinstance(res, dict) else None
    finally:
        try:
            await k.browsers.delete_by_id(b.session_id)
        except Exception:  # noqa: BLE001
            pass


async def compare(p: dict, emit) -> dict:
    from .research import search, short_title
    ident = p.get("model") or short_title(p)
    domains = list(STORES)
    results = await search(f"{p.get('brand') or ''} {ident}".strip(), n=8, chars=1200, include_domains=domains)
    srcs = "\n\n".join(f"[{r['url']}] {r['title']}\n{r['text'][:1100]}" for r in results)
    out = await llm.extract(
        f"Shopper's product: {p.get('title')} (model {p.get('model') or 'unknown'}) at ${p.get('price')} on Amazon.\n\n"
        f"Listings found:\n{srcs}\n\nReturn the price of each listing that is the same product. "
        f"Store name from the domain ({', '.join(STORES.values())}). Mark different models/bundles as same_product=false.",
        OFFERS_SCHEMA)
    offers, seen = [], set()
    for o in out["offers"]:
        if o["same_product"] and o.get("price") and o["store"] not in seen:
            seen.add(o["store"])
            offers.append({**o, "verified": False})
    offers.sort(key=lambda o: o["price"])

    # Verify the cheapest candidate live in a Kernel cloud browser.
    if offers and has("KERNEL_API_KEY"):
        top = offers[0]
        await emit({"type": "tool", "id": "kernel", "name": "kernel", "state": "running",
                    "label": f"Opening {top['store']} in a cloud browser"})
        try:
            live = await asyncio.wait_for(live_price(top["url"]), 70)
            if live and live.get("price"):
                top.update(price=float(live["price"]), verified=True, in_stock=live.get("in_stock"))
            await emit({"type": "tool", "id": "kernel", "name": "kernel", "state": "done",
                        "label": f"Verified {top['store']} live price"})
        except Exception as e:  # noqa: BLE001
            log.warning("kernel verify failed: %r", e)
            await emit({"type": "tool", "id": "kernel", "name": "kernel", "state": "error", "label": "Live check failed"})
        offers.sort(key=lambda o: o["price"])

    cur = p.get("price") or 0
    best = None
    if offers and cur and offers[0]["price"] < cur - 0.5:
        best = {"store": offers[0]["store"], "price": offers[0]["price"], "saving": round(cur - offers[0]["price"], 2),
                "url": offers[0]["url"]}
    rows = [{"store": "Amazon", "price": cur, "url": p.get("url"), "verified": True, "note": "you're here"}] + offers
    return {"id": "stores", "kind": "stores", "offers": rows, "best": best}
