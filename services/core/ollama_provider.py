"""Ollama (Local) embedding and LLM provider implementations."""

from __future__ import annotations

import logging

import httpx

from services.core.providers import EmbeddingProvider, LLMProvider

logger = logging.getLogger(__name__)


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Ollama local embedding provider."""

    def __init__(self, base_url: str, model: str = "mxbai-embed-large"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._dim = 1024  # Default for mxbai-embed-large

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using Ollama's /api/embed or /api/embeddings."""
        all_embeddings: list[list[float]] = []

        with httpx.Client(base_url=self.base_url, timeout=60.0) as client:
            for text in texts:
                logger.info("Ollama embedding text (%d chars)", len(text))
                response = client.post(
                    "/api/embeddings",
                    json={"model": self.model, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                emb = data["embedding"]
                all_embeddings.append(emb)

                # Update dimension on first success
                if not self._dim:
                    self._dim = len(emb)

        return all_embeddings


class OllamaLLMProvider(LLMProvider):
    """Ollama local LLM provider."""

    def __init__(self, base_url: str, model: str = "llama3"):
        self.base_url = base_url.rstrip("/")
        self.model = model

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        logger.info("Ollama generating response (model=%s)", self.model)

        with httpx.Client(base_url=self.base_url, timeout=120.0) as client:
            response = client.post(
                "/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "num_predict": max_tokens,
                        "temperature": temperature,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()
            return data.get("response", "")
