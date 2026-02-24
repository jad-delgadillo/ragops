"""Google Gemini embedding and LLM provider implementations."""

from __future__ import annotations

import logging

import httpx

from services.core.providers import EmbeddingProvider, LLMProvider

logger = logging.getLogger(__name__)


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Google Gemini text embedding provider."""

    PROVIDER = "gemini"
    MODEL = "text-embedding-004"
    DIMENSION = 768

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._base_url = "https://generativelanguage.googleapis.com/v1beta"

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the Gemini Embedding API."""
        all_embeddings: list[list[float]] = []

        with httpx.Client(timeout=60.0) as client:
            for text in texts:
                response = client.post(
                    f"{self._base_url}/models/{self.MODEL}:embedContent",
                    params={"key": self._api_key},
                    json={
                        "model": f"models/{self.MODEL}",
                        "content": {"parts": [{"text": text}]},
                    },
                )
                response.raise_for_status()
                data = response.json()
                all_embeddings.append(data["embedding"]["values"])

        return all_embeddings


class GeminiLLMProvider(LLMProvider):
    """Google Gemini LLM provider."""

    PROVIDER = "gemini"
    MODEL = "gemini-2.0-flash"

    def __init__(self, api_key: str, model: str | None = None):
        self._api_key = api_key
        self._base_url = "https://generativelanguage.googleapis.com/v1beta"
        if model:
            self.MODEL = model

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        logger.info("Gemini generating (model=%s, max_tokens=%d)", self.MODEL, max_tokens)

        with httpx.Client(timeout=120.0) as client:
            response = client.post(
                f"{self._base_url}/models/{self.MODEL}:generateContent",
                params={"key": self._api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

            # Extract text from candidates
            candidates = data.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                return parts[0].get("text", "") if parts else ""
            return ""
