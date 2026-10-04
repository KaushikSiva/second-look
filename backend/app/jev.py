"""Jev (TypeSafe System One): the fast, calibrated BUY / WAIT / SKIP decision over the research signals."""
import httpx

from .config import JEV_MODEL, env, log

URL = "https://api.typesafe.ai/v1/systemone"

VERDICTS = {
    "BUY_NOW": "The price is at or near its real low, reviews are solid, and no store or alternative is clearly better. Buying now is the smart move.",
    "WAIT": "The product is good but the price is inflated versus its history, the discount is fake, or a sale is likely soon. Waiting will probably save money.",
    "SKIP": "Real reviews reveal serious quality or reliability problems, or the hidden yearly costs make it a bad deal regardless of price.",
    "BUY_ALTERNATIVE": "A clearly better value exists: the same product meaningfully cheaper at another store, or an alternative product with better real reviews at a similar or lower price.",
}


async def verdict(signals: dict) -> dict | None:
    key = env("TYPESAFE_API_KEY")
    if not key:
        return None
    body = {"state": signals, "model": JEV_MODEL, "questions": {"verdict": {
        "type": "choice",
        "instructions": "You are a frugal, honest shopping advisor. Given these research signals about a product the shopper is looking at, what should they do?",
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
