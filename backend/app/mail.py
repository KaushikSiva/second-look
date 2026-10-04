"""AgentMail: Second Look's own inbox. It receives forwarded order confirmations, sends price-drop alerts and
writes price-adjustment / return requests to stores, then watches the thread for their reply."""
import asyncio
from typing import Awaitable, Callable

from . import db, llm
from .config import AGENTMAIL_INBOX, USER_EMAIL, env, has, log

_inbox_id: str | None = None


def client():
    from agentmail import AsyncAgentMail
    return AsyncAgentMail(api_key=env("AGENTMAIL_API_KEY"))


async def inbox_id() -> str | None:
    """Get or create the agent's inbox (second-look@agentmail.to)."""
    global _inbox_id
    if _inbox_id or not has("AGENTMAIL_API_KEY"):
        return _inbox_id
    if "@" in AGENTMAIL_INBOX:  # inbox-scoped key: use the inbox as given
        _inbox_id = AGENTMAIL_INBOX
        return _inbox_id
    c = client()
    try:
        return await _find_or_create(c)
    except Exception as e:  # noqa: BLE001
        log.warning("agentmail unavailable: %s", str(e)[:200])
        return None


async def _find_or_create(c) -> str | None:
    global _inbox_id
    try:
        from agentmail.inboxes.types import CreateInboxRequest
        ib = await c.inboxes.create(request=CreateInboxRequest(username=AGENTMAIL_INBOX, display_name="Second Look"))
        _inbox_id = ib.inbox_id
    except Exception:  # noqa: BLE001  already exists
        res = await c.inboxes.list()
        for ib in res.inboxes:
            if ib.inbox_id.split("@")[0] == AGENTMAIL_INBOX:
                _inbox_id = ib.inbox_id
                break
        if not _inbox_id and res.inboxes:
            _inbox_id = res.inboxes[0].inbox_id
    log.info("agentmail inbox: %s", _inbox_id)
    return _inbox_id


async def send(to: str, subject: str, body: str) -> dict:
    card = {"id": f"email-{abs(hash(subject)) % 10**6}", "kind": "email", "to": to, "subject": subject, "body": body}
    ib = await inbox_id()
    if not ib or not to:
        return card | {"status": "draft", "from": ib}
    r = await client().inboxes.messages.send(ib, to=to, subject=subject, text=body)
    await db.q("insert into emails (direction,to_addr,from_addr,subject,body,message_id,thread_id) values ('out',%s,%s,%s,%s,%s,%s) on conflict do nothing",
               to, ib, subject, body, r.message_id, r.thread_id)
    return card | {"status": "sent", "from": ib}


EMAIL_SCHEMA = {"type": "object", "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
                "required": ["subject", "body"]}


async def write_request(kind: str, product: dict, details: str) -> dict:
    """Compose a concise, polite, firm email (price adjustment, return, or seller question)."""
    purchases = await db.q("select * from purchases order by id desc limit 3")
    return await llm.extract(
        f"Write a short, polite but firm email from a shopper (sign as 'Kaushik') — type: {kind}.\n"
        f"Product: {product.get('title')} — current price ${product.get('price')} — {product.get('url')}\n"
        f"Recent purchases on file: {[{k: str(v) for k, v in r.items() if k in ('title', 'store', 'order_id', 'price', 'created_at')} for r in purchases]}\n"
        f"Details from the conversation: {details}\nUnder 120 words. Plain text.", EMAIL_SCHEMA, temperature=0.4)


ORDER_SCHEMA = {"type": "object", "properties": {
    "is_order": {"type": "boolean"}, "title": {"type": "string"}, "store": {"type": "string"}, "order_id": {"type": "string"},
    "price": {"type": "number"}, "return_days": {"type": "integer"}}, "required": ["is_order"]}


async def handle_incoming(msg, emit: Callable[[dict], Awaitable[None]] | None = None):
    """A forwarded order confirmation becomes a tracked purchase (return window + price-drop protection)."""
    text = (msg.text or msg.extracted_text or "")[:6000] if hasattr(msg, "extracted_text") else (msg.text or "")[:6000]
    card = {"id": f"in-{msg.message_id[-8:]}", "kind": "email", "to": msg.to[0] if msg.to else "", "from": msg.from_,
            "subject": msg.subject, "body": text[:400], "status": "received"}
    if emit:
        await emit({"type": "card", "card": card})
    info = await llm.extract(f"Is this an order confirmation? Extract it.\n\nSubject: {msg.subject}\n\n{text}", ORDER_SCHEMA)
    if info.get("is_order"):
        await db.q("""insert into purchases (title, store, order_id, price, return_by) values (%s,%s,%s,%s, current_date + %s)""",
                   info.get("title"), info.get("store"), info.get("order_id"), info.get("price"), info.get("return_days") or 30)
        reply = (f"Got it — I'm tracking \"{info.get('title')}\" (${info.get('price')}). I'll watch the price until your "
                 f"return window closes in {info.get('return_days') or 30} days and claim the difference if it drops.\n\n— Second Look")
        try:
            await client().inboxes.messages.reply(await inbox_id(), msg.message_id, text=reply)
        except Exception as e:  # noqa: BLE001
            log.warning("reply failed: %r", e)
        if emit:
            await emit({"type": "card", "card": {"id": f"track-{msg.message_id[-8:]}", "kind": "email", "to": msg.from_,
                                                 "subject": "Re: " + (msg.subject or ""), "body": reply, "status": "sent"}})
    return info


async def poll(emit_all: Callable[[dict], Awaitable[None]]):
    """Poll the inbox for new inbound mail (no public webhook URL needed during the hackathon)."""
    if not await inbox_id():
        return
    seen = {r["message_id"] for r in await db.q("select message_id from emails where message_id is not null")}
    first = True
    while True:
        try:
            res = await client().inboxes.messages.list(await inbox_id(), limit=20)
            for m in reversed(res.messages):
                if m.message_id in seen:
                    continue
                seen.add(m.message_id)
                if first or "sent" in (m.labels or []):
                    continue
                full = await client().inboxes.messages.get(await inbox_id(), m.message_id)
                await db.q("insert into emails (direction,to_addr,from_addr,subject,body,message_id,thread_id) values ('in',%s,%s,%s,%s,%s,%s) on conflict do nothing",
                           ",".join(full.to or []), full.from_, full.subject, (full.text or "")[:8000], full.message_id, full.thread_id)
                await handle_incoming(full, emit_all)
            first = False
        except Exception as e:  # noqa: BLE001
            log.warning("inbox poll: %r", e)
        await asyncio.sleep(8)


async def alert_user(subject: str, body: str) -> dict | None:
    if USER_EMAIL:
        return await send(USER_EMAIL, subject, body)
    return None
