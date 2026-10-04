"""research_product: reviews ‖ price ‖ stores ‖ alternatives run concurrently, each streams its card the moment it
lands, then Jev turns the combined signals into one BUY_NOW / WAIT / SKIP / BUY_ALTERNATIVE verdict."""
import asyncio
import statistics
from typing import Awaitable, Callable

from exa_py import AsyncExa

from . import db, jev, llm, stores
from .config import env, log

Emit = Callable[[dict], Awaitable[None]]

_exa: AsyncExa | None = None


def exa() -> AsyncExa:
    global _exa
    if _exa is None:
        _exa = AsyncExa(env("EXA_API_KEY"))
    return _exa


def short_title(p: dict) -> str:
    t = p.get("title") or ""
    return " ".join(t.replace(",", " ").split()[:9])


async def search(query: str, n: int = 6, chars: int = 1500, **kw) -> list[dict]:
    r = await exa().search(query, num_results=n, contents={"text": {"max_characters": chars}}, type=kw.pop("type", "fast"), **kw)
    return [{"title": x.title, "url": x.url, "text": x.text or ""} for x in r.results]


# ---------------------------------------------------------------- reviews
REVIEWS_SCHEMA = {
    "type": "object",
    "properties": {
        "real_rating": {"type": "number", "description": "Honest 1-5 rating from independent sources, discounting incentivized/fake praise"},
        "incentivized_pct": {"type": "integer", "description": "Estimated % of the Amazon review snippets that look incentivized, fake or low-information"},
        "pros": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "cons": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "top_complaint": {"type": "string"},
        "summary": {"type": "string", "description": "One spoken sentence a friend would say"},
        "used_sources": {"type": "array", "items": {"type": "integer"}, "description": "indexes of sources actually used"},
    },
    "required": ["real_rating", "incentivized_pct", "pros", "cons", "top_complaint", "summary", "used_sources"],
}


async def reviews(p: dict) -> dict:
    name = short_title(p)
    results = await search(f"{name} honest review reddit long term problems", n=6,
                           exclude_domains=["amazon.com"])
    srcs = "\n\n".join(f"[{i}] {r['title']} ({r['url']})\n{r['text'][:1400]}" for i, r in enumerate(results))
    snippets = "\n".join(f"- {s[:300]}" for s in (p.get("review_snippets") or [])[:8])
    out = await llm.extract(
        f"Product: {p.get('title')}\nAmazon shows {p.get('rating')} stars from {p.get('review_count')} reviews.\n\n"
        f"Amazon review snippets on the page:\n{snippets or '(none captured)'}\n\nIndependent sources:\n{srcs}\n\n"
        "Write an honest assessment. Short pros/cons (max 8 words each).", REVIEWS_SCHEMA)
    used = [results[i] for i in out.get("used_sources", []) if 0 <= i < len(results)] or results[:3]
    return {"id": "reviews", "kind": "reviews", "shown_rating": p.get("rating"), "real_rating": round(out["real_rating"], 1),
            "incentivized_pct": out["incentivized_pct"], "pros": out["pros"], "cons": out["cons"],
            "top_complaint": out["top_complaint"], "summary": out["summary"],
            "sources": [{"title": r["title"], "url": r["url"]} for r in used[:4]]}


# ---------------------------------------------------------------- price history
async def price(p: dict, key: str) -> dict:
    hist = await db.history(key)
    cur = p.get("price")
    prices = [h["price"] for h in hist] or ([cur] if cur else [])
    low, high = (min(prices), max(prices)) if prices else (cur, cur)
    avg = round(statistics.mean(prices), 2) if prices else cur
    lp = p.get("list_price")
    # "Was $X" is fake when the product hasn't actually sold near X in the tracked window
    span_days = (hist[-1]["t"] - hist[0]["t"]) / 86_400_000 if len(hist) >= 2 else 0
    # only call a discount fake with a real track record (30+ days without ever selling near the "was" price)
    fake = bool(lp and cur and lp > cur * 1.05 and span_days >= 30 and high < lp * 0.93)
    if span_days < 7:
        note = "Just started tracking this one; every price Second Look sees is saved in Neon."
    elif cur and low and cur <= low * 1.02:
        note = "At its lowest tracked price."
    elif cur and avg and cur > avg * 1.05:
        note = f"{round((cur / low - 1) * 100)}% above its 180-day low of ${low:.2f}."
    else:
        note = "Around its usual price."
    if fake:
        note = f"\"Was ${lp:.2f}\" is a fake reference — it hasn't sold near that. " + note
    return {"id": "price", "kind": "price", "current": cur, "low": low, "avg": avg, "high": high, "list_price": lp,
            "fake_discount": fake, "history": [{"t": h["t"], "price": h["price"]} for h in hist], "note": note,
            "points": len(hist), "span_days": round(span_days), "demo_data": any(h["source"] == "seed" for h in hist)}


# ---------------------------------------------------------------- alternatives + lifetime cost
ALT_SCHEMA = {
    "type": "object",
    "properties": {
        "alternatives": {"type": "array", "maxItems": 2, "items": {"type": "object", "properties": {
            "title": {"type": "string"}, "price": {"type": "number"}, "why": {"type": "string"}, "url": {"type": "string"},
            "real_rating": {"type": "number"}}, "required": ["title", "why", "url"]}},
        "yearly_extra": {"type": "number", "description": "Recurring yearly cost of owning it in USD (filters, ink, refills, subscriptions); 0 if none"},
        "cost_items": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
    "required": ["alternatives", "yearly_extra", "cost_items"],
}


async def alternatives(p: dict) -> tuple[dict, dict]:
    name = short_title(p)
    budget = f" under ${round((p.get('price') or 0) * 1.25)}" if p.get("price") else ""
    alt_res, cost_res = await asyncio.gather(
        search(f"best alternatives to {name}{budget} 2026", n=5),
        search(f"{name} replacement filter ink refill subscription cost per year", n=4, chars=900))
    srcs = "\n\n".join(f"[{r['url']}] {r['title']}\n{r['text'][:1200]}" for r in alt_res + cost_res)
    out = await llm.extract(
        f"Shopper is viewing: {p.get('title')} at ${p.get('price')}.\n\nSources:\n{srcs}\n\n"
        "Pick up to 2 genuinely better-value alternatives (different products, similar or lower price, better reviews). "
        "Use a source URL for each. Also estimate the recurring yearly cost of owning the viewed product.", ALT_SCHEMA)
    alts = {"id": "alternatives", "kind": "alternatives", "items": out["alternatives"]}
    cost = {"id": "cost", "kind": "cost", "yearly_extra": out["yearly_extra"], "items": out["cost_items"]}
    return alts, cost


# ---------------------------------------------------------------- orchestration
async def _run(name: str, label: str, coro, emit: Emit):
    await emit({"type": "tool", "id": name, "name": name, "state": "running", "label": label})
    try:
        res = await coro
        await emit({"type": "tool", "id": name, "name": name, "state": "done", "label": label})
        return res
    except Exception as e:  # noqa: BLE001
        log.exception("%s failed", name)
        await emit({"type": "tool", "id": name, "name": name, "state": "error", "label": label})
        return e


async def research_product(p: dict, emit: Emit, focus: str = "all") -> dict:
    key = await db.record_product(p)
    want = {"all": {"reviews", "price", "stores", "alternatives"}, "reviews": {"reviews"}, "price": {"price", "stores"},
            "stores": {"stores"}, "alternatives": {"alternatives"}}.get(focus, {"reviews", "price", "stores", "alternatives"})

    async def card(name, label, coro):
        res = await _run(name, label, coro, emit)
        if isinstance(res, Exception):
            return None
        for c in (res if isinstance(res, tuple) else (res,)):
            if c:
                await emit({"type": "card", "card": c})
        return res

    jobs = {}
    if "reviews" in want:
        jobs["reviews"] = card("reviews", "Reading Reddit & expert reviews", reviews(p))
    if "price" in want:
        jobs["price"] = card("price", "Checking 180-day price history", price(p, key))
    if "stores" in want:
        jobs["stores"] = card("stores", "Comparing Walmart, Best Buy, Target", stores.compare(p, emit))
    if "alternatives" in want:
        jobs["alternatives"] = card("alternatives", "Finding better-value alternatives", alternatives(p))
    results = dict(zip(jobs, await asyncio.gather(*jobs.values())))

    rv, pr, st = results.get("reviews"), results.get("price"), results.get("stores")
    alts, cost = results.get("alternatives") or (None, None)

    savings = 0
    if st and st.get("best"):
        savings = int(round(st["best"]["saving"] * 100))
        await emit({"type": "savings", "total_cents": await db.add_saving("cheaper_store", savings,
                                                                           f"{st['best']['store']} cheaper for {short_title(p)}")})

    derived = {
        "price_vs_low_pct": pr and pr["low"] and pr["current"] and round((pr["current"] / pr["low"] - 1) * 100),
        "price_vs_avg_pct": pr and pr["avg"] and pr["current"] and round((pr["current"] / pr["avg"] - 1) * 100),
        "fake_discount": pr and pr["fake_discount"],
        "real_rating": rv and rv["real_rating"],
        "cheaper_elsewhere": st and st.get("best"),
    }
    signals = {
        "derived": derived,
        "product": {"title": p.get("title"), "price": p.get("price")},
        "reviews": rv and {k: rv[k] for k in ("shown_rating", "real_rating", "incentivized_pct", "top_complaint")},
        "price": pr and {k: pr[k] for k in ("current", "low", "avg", "high", "list_price", "fake_discount", "note")},
        "other_stores": st and {"best": st.get("best"), "offers": [{k: o.get(k) for k in ("store", "price")} for o in st["offers"]]},
        "alternatives": alts and [{k: a.get(k) for k in ("title", "price", "real_rating")} for a in alts["items"]],
        "yearly_extra_cost": cost and cost["yearly_extra"],
    }
    summary = {"signals": signals}
    if focus == "all":
        v = await _run("verdict", "Jev deciding: buy, wait or skip", jev.verdict(signals), emit)
        if not v or isinstance(v, Exception):
            v = {"verdict": "WAIT" if pr and pr["fake_discount"] else "BUY_NOW", "confidence": None, "probabilities": {}}
        reasons = []
        if pr:
            reasons.append(pr["note"])
        if rv:
            reasons.append(f"Real rating ≈ {rv['real_rating']}★ (shown {rv['shown_rating']}★). {rv['top_complaint']}")
        if st and st.get("best"):
            reasons.append(f"{st['best']['store']} has it ${st['best']['saving']:.2f} cheaper.")
        if cost and cost["yearly_extra"]:
            reasons.append(f"Hidden cost ≈ ${cost['yearly_extra']:.0f}/yr ({', '.join(cost['items'][:2])}).")
        if v["verdict"] == "BUY_ALTERNATIVE" and alts and alts["items"]:
            reasons.append(f"Better pick: {alts['items'][0]['title']}.")
        headline = {"BUY_NOW": "Good deal — buy it", "WAIT": "Wait — this price isn't the real deal",
                    "SKIP": "Skip it", "BUY_ALTERNATIVE": "There's a better buy"}[v["verdict"]]
        await emit({"type": "card", "card": {"id": "verdict", "kind": "verdict", **v, "headline": headline, "reasons": reasons[:4]}})
        summary.update(verdict=v["verdict"], confidence=v["confidence"], headline=headline, reasons=reasons)
    return summary
