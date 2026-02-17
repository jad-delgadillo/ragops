"""Anthropic Claude LLM provider implementation."""

from __future__ import annotations

import logging

import httpx

from services.core.providers import LLMProvider

logger = logging.getLogger(__name__)


class ClaudeLLMProvider(LLMProvider):
    """Anthropic Claude LLM provider (LLM only — no embeddings API)."""

    MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        if model:
            self.MODEL = model

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        logger.info("Claude generating (model=%s, max_tokens=%d)", self.MODEL, max_tokens)

        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.MODEL,
                    "max_tokens": max_tokens,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": temperature,
                },
            )
            response.raise_for_status()
            data = response.json()

            # Extract text from content blocks
            content = data.get("content", [])
            texts = [block["text"] for block in content if block.get("type") == "text"]
            return "\n".join(texts)
