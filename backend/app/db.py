"""Neon Postgres: the agent's memory (products, price history, watchlist, purchases, savings, mail)."""
import hashlib
from contextlib import asynccontextmanager

import psycopg
from psycopg.rows import dict_row

from .config import env, log

SCHEMA = """
create table if not exists products (
  key text primary key, title text, url text, site text, asin text, model text, image text,
  last_price numeric, updated_at timestamptz default now());
create table if not exists price_history (
  id bigserial primary key, product_key text not null, price numeric not null, store text default 'amazon',
  source text default 'observed', observed_at timestamptz default now());
create index if not exists price_history_key on price_history (product_key, observed_at);
create table if not exists watchlist (
  id bigserial primary key, product_key text, title text, url text, target_price numeric, current_price numeric,
  created_at timestamptz default now(), triggered_at timestamptz);
create table if not exists purchases (
  id bigserial primary key, product_key text, title text, store text, order_id text, price numeric,
  return_by date, created_at timestamptz default now());
create table if not exists savings (
  id bigserial primary key, kind text, amount_cents int, note text, created_at timestamptz default now());
create table if not exists emails (
  id bigserial primary key, direction text, to_addr text, from_addr text, subject text, body text,
  message_id text unique, thread_id text, created_at timestamptz default now());
create table if not exists memories (
  id bigserial primary key, note text, created_at timestamptz default now());
"""


def product_key(p: dict) -> str:
    if p.get("asin"):
        return "asin:" + p["asin"]
    return "url:" + hashlib.sha1((p.get("url") or p.get("title") or "").split("?")[0].encode()).hexdigest()[:16]


@asynccontextmanager
async def conn():
    c = await psycopg.AsyncConnection.connect(env("DATABASE_URL"), row_factory=dict_row, autocommit=True)
    try:
        yield c
    finally:
        await c.close()


async def q(sql: str, *args) -> list[dict]:
    async with conn() as c:
        cur = await c.execute(sql, args or None)
        return await cur.fetchall() if cur.description else []


async def init():
    async with conn() as c:
        await c.execute(SCHEMA)
    log.info("db ready")


async def record_product(p: dict) -> str:
    key = product_key(p)
    await q("""insert into products (key,title,url,site,asin,model,image,last_price) values (%s,%s,%s,%s,%s,%s,%s,%s)
               on conflict (key) do update set title=excluded.title, url=excluded.url, last_price=excluded.last_price,
               image=excluded.image, updated_at=now()""",
            key, p.get("title"), p.get("url"), p.get("site"), p.get("asin"), p.get("model"), p.get("image"), p.get("price"))
    if p.get("price"):
        # one observation per hour is plenty
        recent = await q("select 1 from price_history where product_key=%s and observed_at > now() - interval '1 hour' limit 1", key)
        if not recent:
            await q("insert into price_history (product_key, price) values (%s,%s)", key, p["price"])
    return key


async def history(key: str, days: int = 180) -> list[dict]:
    return await q("""select price::float as price, extract(epoch from observed_at)*1000 as t, source from price_history
                      where product_key=%s and store='amazon' and observed_at > now() - make_interval(days => %s)
                      order by observed_at""", key, days)


async def add_saving(kind: str, cents: int, note: str) -> int:
    await q("insert into savings (kind, amount_cents, note) values (%s,%s,%s)", kind, cents, note)
    return await total_savings()


async def total_savings() -> int:
    r = await q("select coalesce(sum(amount_cents),0)::int as t from savings")
    return r[0]["t"]


async def memories(limit: int = 20) -> list[str]:
    return [r["note"] for r in await q("select note from memories order by id desc limit %s", limit)]
