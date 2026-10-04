"""Jev (TypeSafe System One): the fast, calibrated BUY / WAIT / SKIP decision over the research signals."""
import httpx

from .config import JEV_MODEL, env, log

URL = "https://api.typesafe.ai/v1/systemone"

VERDICTS = {
    "BUY_NOW": "Price is at or within ~5% of its tracked low, there is no real fake discount, the real rating is about 4.0 or higher, and no other store or alternative is meaningfully better. A good deal on a good product.",
    "WAIT": "The product itself is fine, but today's price is clearly above its usual or low price, or the advertised discount is fake. Waiting for the price to come back down will likely save money.",
    "SKIP": "Only when the product itself is bad: real rating below about 3.6, or widespread reports of it failing, breaking or being unsafe. Ordinary complaints and routine filter/refill costs are NOT reasons to skip.",
    "BUY_ALTERNATIVE": "The identical product is meaningfully cheaper at another store (verified offer), or a listed alternative has a clearly higher real rating at a similar or lower price.",
}


async def verdict(signals: dict) -> dict | None:
    key = env("TYPESAFE_API_KEY")
    if not key:
        return None
    body = {"state": signals, "model": JEV_MODEL, "questions": {"verdict": {
        "type": "choice",
        "instructions": "You are a frugal, honest shopping advisor. Weigh the derived signals (price_vs_low_pct, real_rating, fake_discount, cheaper_elsewhere) first. What should the shopper do right now?",
        "criteria": VERDICTS}}}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(URL, json=body, headers={"Authorization": f"Bearer {key}"})
            r.raise_for_status()
            a = r.json()["answers"]["verdict"]
        return {"verdict": a["choice"], "confidence": a.get("confidence"), "probabilities": a.get("probabilities") or {}}
    except Exception as e:  # noqa: BLE001
        log.warning("jev verdict failed: %r", e)
        return None
