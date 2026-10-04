"""Bridges one side-panel WebSocket to one Gemini 3.8 Live session. Gemini hears the shopper, sees the tab (1 fps
screenshots), and calls our tools NON_BLOCKING: research runs in the background while the conversation continues,
and results are handed back WHEN_IDLE so Gemini speaks them at a natural pause."""
import asyncio
import base64
import json
import os
import time
import wave

from google.genai import types

from . import db, mail, research
from .config import LIVE_MODEL, LIVE_VOICE, env, log

RECORD_DIR = env("RECORD_AUDIO_DIR")
from .llm import client

SYSTEM = """You are Second Look, a sharp, warm, frugal shopping friend living in the shopper's browser side panel.
You can see their screen (periodic screenshots) and you get structured page data for the product they're viewing.

How you work:
- When they ask anything like "should I buy this", "is this a good price", "is it worth it": call research_product
  (focus "all") immediately. It runs in the background — keep talking naturally while it works (e.g. ask what they'll
  use it for) and NEVER invent numbers before results arrive. Cards appear in the panel as each part finishes.
- For narrower questions use research_product with focus "reviews", "price", "stores" or "alternatives".
- "Tell me / watch if it drops", "alert me under $X" → watch_price.
- Price adjustments, returns, questions to a seller → send_email (to the store/seller address they give, or leave
  'to' empty to just draft it).
- Remember durable preferences ("I hate loud fans", "my budget is $150") with remember.
- When results come back: lead with the verdict in one sentence, then the 2 most important reasons with real numbers.
  Be concise and conversational — this is voice. Don't read URLs aloud. Point at the cards instead of listing everything.
- If the screen shows something the page data doesn't (a cart, a coupon, a different product), use what you see.
"""

TOOLS = [types.Tool(function_declarations=[
    types.FunctionDeclaration(
        name="research_product", behavior=types.Behavior.NON_BLOCKING,
        description="Research the product currently on screen: real reviews, price history & fake-discount check, "
                    "same product at other stores (live-verified), better alternatives and lifetime cost; returns a "
                    "BUY_NOW/WAIT/SKIP/BUY_ALTERNATIVE verdict.",
        parameters_json_schema={"type": "object", "properties": {
            "focus": {"type": "string", "enum": ["all", "reviews", "price", "stores", "alternatives"]}}}),
    types.FunctionDeclaration(
        name="watch_price", behavior=types.Behavior.NON_BLOCKING,
        description="Watch the current product and alert the shopper by email when it drops to the target price.",
        parameters_json_schema={"type": "object", "properties": {"target_price": {"type": "number"}},
                                "required": ["target_price"]}),
    types.FunctionDeclaration(
        name="send_email", behavior=types.Behavior.NON_BLOCKING,
        description="Write and send an email from Second Look's own inbox: price adjustment request, return request, "
                    "or question to a seller. Leave 'to' empty to only draft it.",
        parameters_json_schema={"type": "object", "properties": {
            "kind": {"type": "string", "enum": ["price_adjustment", "return", "seller_question"]},
            "to": {"type": "string"}, "details": {"type": "string"}}, "required": ["kind", "details"]}),
    types.FunctionDeclaration(
        name="remember", behavior=types.Behavior.NON_BLOCKING,
        description="Save a durable shopper preference or fact for future shopping.",
        parameters_json_schema={"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}),
])]


class Bridge:
    def __init__(self, ws, hub):
        self.ws = ws
        self.hub = hub
        self.product: dict | None = None
        self.session = None
        self.tasks: set[asyncio.Task] = set()
        self.send_lock = asyncio.Lock()
        self.audio_log: list[tuple[float, bytes]] = []  # (wall time, 24 kHz PCM) when RECORD_AUDIO_DIR is set

    async def emit(self, msg: dict):
        async with self.send_lock:
            try:
                await self.ws.send_text(json.dumps(msg, default=str))
            except Exception:  # noqa: BLE001
                pass

    # ---------------------------------------------------------------- tools
    async def run_tool(self, fc: types.FunctionCall):
        args = fc.args or {}
        try:
            if not self.product and fc.name in ("research_product", "watch_price"):
                result = {"error": "No product detected on the current tab. Ask the shopper to open a product page."}
            elif fc.name == "research_product":
                result = await research.research_product(self.product, self.emit, args.get("focus", "all"))
            elif fc.name == "watch_price":
                p, target = self.product, float(args["target_price"])
                key = await db.record_product(p)
                await db.q("insert into watchlist (product_key,title,url,target_price,current_price) values (%s,%s,%s,%s,%s)",
                           key, p.get("title"), p.get("url"), target, p.get("price"))
                await self.emit({"type": "card", "card": {"id": f"watch-{key}", "kind": "watch", "title": p.get("title"),
                                                          "target_price": target, "current": p.get("price")}})
                result = {"ok": True, "watching": p.get("title"), "target_price": target,
                          "how": "Checked every few hours; Second Look emails when it hits the target."}
            elif fc.name == "send_email":
                p = self.product or {}
                await self.emit({"type": "tool", "id": "email", "name": "email", "state": "running", "label": "Writing the email"})
                draft = await mail.write_request(args.get("kind", "seller_question"), p, args.get("details", ""))
                card = await mail.send(args.get("to", ""), draft["subject"], draft["body"])
                await self.emit({"type": "tool", "id": "email", "name": "email", "state": "done",
                                 "label": "Email sent" if card["status"] == "sent" else "Email drafted"})
                await self.emit({"type": "card", "card": card})
                result = {"status": card["status"], "subject": draft["subject"], "from": card.get("from")}
            elif fc.name == "remember":
                await db.q("insert into memories (note) values (%s)", args["note"])
                result = {"ok": True}
            else:
                result = {"error": f"unknown tool {fc.name}"}
        except Exception as e:  # noqa: BLE001
            log.exception("tool %s failed", fc.name)
            result = {"error": str(e)[:300]}
        if self.session:
            try:
                await self.session.send_tool_response(function_responses=[types.FunctionResponse(
                    id=fc.id, name=fc.name, response={"result": result},
                    scheduling=types.FunctionResponseScheduling.WHEN_IDLE)])
            except Exception as e:  # noqa: BLE001
                log.warning("tool response failed: %r", e)

    # ---------------------------------------------------------------- gemini → panel
    async def pump(self):
        while True:
            async for msg in self.session.receive():
                sc = msg.server_content
                if sc:
                    if sc.interrupted:
                        await self.emit({"type": "interrupted"})
                    if sc.model_turn:
                        for part in sc.model_turn.parts or []:
                            if part.inline_data and part.inline_data.data:
                                if RECORD_DIR:
                                    self.audio_log.append((time.time(), part.inline_data.data))
                                await self.emit({"type": "audio", "data": base64.b64encode(part.inline_data.data).decode()})
                    if sc.input_transcription and sc.input_transcription.text:
                        await self.emit({"type": "transcript", "role": "user", "text": sc.input_transcription.text,
                                         "final": bool(sc.input_transcription.finished)})
                    if sc.output_transcription and sc.output_transcription.text:
                        await self.emit({"type": "transcript", "role": "agent", "text": sc.output_transcription.text,
                                         "final": False})
                    if sc.turn_complete:
                        await self.emit({"type": "transcript", "role": "agent", "text": "", "final": True})
                if msg.tool_call:
                    for fc in msg.tool_call.function_calls or []:
                        t = asyncio.create_task(self.run_tool(fc))
                        self.tasks.add(t)
                        t.add_done_callback(self.tasks.discard)
                if msg.go_away:
                    log.info("go_away: %s", msg.go_away)

    # ---------------------------------------------------------------- panel → gemini
    async def context_text(self) -> str:
        mem = await db.memories(10)
        p = self.product
        page = json.dumps({k: p.get(k) for k in ("title", "price", "list_price", "rating", "review_count", "site", "coupon")}) if p else "none"
        return f"[context] Product on screen: {page}. Shopper preferences: {mem or 'none yet'}."

    async def run(self):
        cfg = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM,
            tools=TOOLS,
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            speech_config=types.SpeechConfig(voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=LIVE_VOICE))),
            context_window_compression=types.ContextWindowCompressionConfig(sliding_window=types.SlidingWindow()),
        )
        await self.emit({"type": "status", "state": "connecting"})
        async with client().aio.live.connect(model=LIVE_MODEL, config=cfg) as session:
            self.session = session
            await self.emit({"type": "status", "state": "live"})
            await self.emit({"type": "savings", "total_cents": await db.total_savings()})
            await session.send_realtime_input(text=await self.context_text())
            pump = asyncio.create_task(self.pump())
            try:
                while True:
                    raw = await self.ws.receive_text()
                    m = json.loads(raw)
                    t = m.get("type")
                    if t == "audio":
                        await session.send_realtime_input(audio=types.Blob(data=base64.b64decode(m["data"]),
                                                                           mime_type="audio/pcm;rate=16000"))
                    elif t == "frame":
                        await session.send_realtime_input(video=types.Blob(data=base64.b64decode(m["data"]),
                                                                           mime_type="image/jpeg"))
                    elif t == "page":
                        await self.set_product(m.get("product"))
                    elif t == "text":
                        await self.emit({"type": "transcript", "role": "user", "text": m["text"], "final": True})
                        await session.send_realtime_input(text=m["text"])
                    elif t == "stop":
                        break
                    if pump.done():
                        pump.result()
            finally:
                pump.cancel()
                self.session = None
                self.save_audio()

    def save_audio(self):
        """Lay the agent's voice onto a wall-clock timeline (for muxing into screen recordings of the demo)."""
        if not RECORD_DIR or not self.audio_log:
            return
        t0, rate, pcm, cursor = self.audio_log[0][0], 24000, bytearray(), 0.0
        for t, chunk in self.audio_log:
            start = max(t - t0, cursor)
            pcm.extend(b"\0\0" * int((start - len(pcm) / 2 / rate) * rate))
            pcm.extend(chunk)
            cursor = len(pcm) / 2 / rate
        os.makedirs(RECORD_DIR, exist_ok=True)
        path = os.path.join(RECORD_DIR, f"agent_{t0:.3f}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(bytes(pcm))
        log.info("saved agent audio %s", path)
        self.audio_log = []

    async def set_product(self, p: dict | None):
        if not p or not p.get("title"):
            return
        changed = not self.product or self.product.get("url") != p.get("url")
        self.product = p
        try:
            await db.record_product(p)
        except Exception as e:  # noqa: BLE001
            log.warning("record_product: %r", e)
        if changed and self.session:
            await self.session.send_realtime_input(text=await self.context_text())
