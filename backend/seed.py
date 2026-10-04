"""Seed realistic 180-day price history for demo products (rows tagged source='seed' so it's never mistaken for
observed data). Usage: python seed.py ASIN CURRENT_PRICE [TYPICAL_LOW]"""
import asyncio
import random
import sys

from app import db


async def main(asin: str, current: float, low: float | None):
    low = low or round(current * 0.78, 2)
    key = "asin:" + asin
    await db.init()
    await db.q("delete from price_history where product_key=%s and source='seed'", key)
    rnd = random.Random(asin)
    rows = []
    for d in range(180, 0, -2):
        base = low + (current - low) * 0.55
        if d in range(96, 90, -1) or d in range(10, 6, -1):   # past sale dips (Prime Day / last month)
            base = low
        p = round(base * rnd.uniform(0.98, 1.03), 2)
        rows.append((key, p, d))
    async with db.conn() as c:
        async with c.cursor() as cur:
            await cur.executemany("insert into price_history (product_key, price, source, observed_at) values (%s,%s,'seed', now() - make_interval(days => %s))", rows)
    print("seeded", key, "low", low)

if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2]), float(sys.argv[3]) if len(sys.argv) > 3 else None))
