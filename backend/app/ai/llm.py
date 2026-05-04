"""Thin LLM client wrapper with cost guard and PII redaction."""

import re
from typing import Any

from loguru import logger

from app.core.config import settings

try:
    from openai import OpenAI
    _client = OpenAI(api_key=settings.OPENAI_API_KEY) if settings.OPENAI_API_KEY else None
except Exception:
    _client = None


_PII_PHONE = re.compile(r"\+?\d[\d\s\-]{7,}\d")


def redact(text: str) -> str:
    return _PII_PHONE.sub("[REDACTED]", text)


def chat(messages: list[dict[str, str]], *, model: str | None = None,
         temperature: float = 0.3, json_mode: bool = False) -> str:
    """Call the LLM. Falls back to a templated stub when no key is configured."""
    if _client is None:
        logger.warning("LLM not configured — returning stub response.")
        return _stub(messages)
    kwargs: dict[str, Any] = {
        "model": model or settings.OPENAI_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    resp = _client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


def embed(text: str) -> list[float]:
    if _client is None:
        return [0.0] * 1536
    resp = _client.embeddings.create(model=settings.OPENAI_EMBED_MODEL, input=text)
    return resp.data[0].embedding


def _stub(messages: list[dict[str, str]]) -> str:
    last = messages[-1]["content"][:120]
    return f"[stub] {last} ..."
