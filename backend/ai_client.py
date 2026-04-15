"""OpenRouter AI client — uses cheapest model per use case."""

import os
import logging

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_BASE = "https://openrouter.ai/api/v1/chat/completions"


async def ai_complete(
    prompt: str,
    system: str = "",
    model: str = "google/gemma-3-4b-it",
) -> str:
    """Call OpenRouter with the cheapest available model.

    Returns the model's text response, or empty string on failure / no API key.
    """
    if not OPENROUTER_API_KEY:
        return ""

    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                OPENROUTER_BASE,
                headers={
                    "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                    "HTTP-Referer": "https://datasnoop.be",
                    "X-Title": "Datasnoop",
                },
                json={
                    "model": model,
                    "messages": messages,
                    "max_tokens": 500,
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            logger.warning(
                "OpenRouter returned %s: %s", resp.status_code, resp.text[:200]
            )
    except Exception as e:
        logger.exception("OpenRouter request failed: %s", e)

    return ""
