"""Groq LLM provider implementation (OpenAI-compatible API)."""

from __future__ import annotations

import logging

from openai import OpenAI

from services.core.providers import LLMProvider

logger = logging.getLogger(__name__)


class GroqLLMProvider(LLMProvider):
    """Groq LLM provider — ultra-fast inference.

    Uses the OpenAI-compatible API, so we reuse the openai SDK
    with a custom base_url.
    """

    PROVIDER = "groq"
    MODEL = "llama-3.3-70b-versatile"

    def __init__(self, api_key: str, model: str | None = None):
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
        )
        if model:
            self.MODEL = model

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        logger.info("Groq generating (model=%s, max_tokens=%d)", self.MODEL, max_tokens)

        response = self._client.chat.completions.create(
            model=self.MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
