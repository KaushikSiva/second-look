"""Small structured-output helper on Gemini Flash (used by the background research, not the live voice)."""
import asyncio
import json

from google import genai
from google.genai import types

from .config import TEXT_MODEL, env

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=env("GEMINI_API_KEY"))
    return _client


async def extract(prompt: str, schema: dict, temperature: float = 0.2) -> dict:
    """Retries 503 'high demand' / transient errors with backoff."""
    models = [TEXT_MODEL] + [m for m in FALLBACKS if m != TEXT_MODEL]
    for attempt in range(5):
        try:
            # a slow Flash call is as bad as a failed one in a live conversation: cap it and fall through
            return await asyncio.wait_for(_extract(models[min(attempt, len(models) - 1)], prompt, schema, temperature), 12)
        except Exception as e:  # noqa: BLE001
            if attempt == 4 or not (isinstance(e, asyncio.TimeoutError) or
                                    any(x in str(e) for x in ("503", "UNAVAILABLE", "disconnected", "429", "500"))):
                raise
            await asyncio.sleep(0.2)


# Flash 3.8 sometimes returns 503 "high demand"; fall through to older Flash models rather than fail a card.
FALLBACKS = ["gemini-3.7-flash", "gemini-3.5-flash", "gemini-flash-latest"]


async def _extract(model: str, prompt: str, schema: dict, temperature: float) -> dict:
    r = await client().aio.models.generate_content(
        model=model, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema,
                                           temperature=temperature,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return json.loads(r.text)
