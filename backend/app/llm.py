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
    for attempt in range(4):
        try:
            return await _extract(prompt, schema, temperature)
        except Exception as e:  # noqa: BLE001
            if attempt == 3 or not any(x in str(e) for x in ("503", "UNAVAILABLE", "disconnected", "429", "500")):
                raise
            await asyncio.sleep(0.8 * (attempt + 1))


async def _extract(prompt: str, schema: dict, temperature: float) -> dict:
    r = await client().aio.models.generate_content(
        model=TEXT_MODEL, contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json", response_json_schema=schema,
                                           temperature=temperature,
                                           thinking_config=types.ThinkingConfig(thinking_budget=0)))
    return json.loads(r.text)
