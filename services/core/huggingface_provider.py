"""Hugging Face Inference API embedding provider implementation."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from services.core.providers import EmbeddingProvider

logger = logging.getLogger(__name__)


def _mean_pool_vectors(rows: list[list[float]]) -> list[float]:
    if not rows:
        return []
    width = len(rows[0])
    if width == 0:
        return []

    totals = [0.0] * width
    for row in rows:
        if len(row) != width:
            raise ValueError("Inconsistent Hugging Face embedding row width")
        for idx, value in enumerate(row):
            totals[idx] += value
    count = float(len(rows))
    return [value / count for value in totals]


def _parse_embedding_payload(payload: Any) -> list[float]:
    """Normalize Hugging Face embedding responses into one vector."""
    if isinstance(payload, list) and payload and all(isinstance(v, (int, float)) for v in payload):
        return [float(v) for v in payload]

    # Some models return per-token vectors; mean-pool these rows.
    if isinstance(payload, list) and payload and all(isinstance(row, list) for row in payload):
        if all(
            isinstance(value, (int, float))
            for row in payload
            for value in row
        ):
            return _mean_pool_vectors([[float(v) for v in row] for row in payload])

    raise ValueError("Unsupported Hugging Face embedding response format")


class HuggingFaceEmbeddingProvider(EmbeddingProvider):
    """Hugging Face embedding provider using the hosted Inference API."""

    PROVIDER = "huggingface"

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "sentence-transformers/all-MiniLM-L6-v2",
        base_url: str = "https://api-inference.huggingface.co",
        dimension: int = 384,
    ):
        if not api_key:
            raise ValueError("HUGGINGFACE_API_KEY is required for Hugging Face embeddings")
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self._dim = max(1, int(dimension))

    @property
    def dimension(self) -> int:
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts via Hugging Face Inference API."""
        if not texts:
            return []

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
        }

        embeddings: list[list[float]] = []
        with httpx.Client(base_url=self.base_url, timeout=60.0) as client:
            for text in texts:
                response = client.post(
                    f"/models/{self.model}",
                    headers=headers,
                    json={
                        "inputs": text,
                        "options": {"wait_for_model": True},
                    },
                )
                response.raise_for_status()
                payload = response.json()
                if isinstance(payload, dict) and payload.get("error"):
                    raise RuntimeError(str(payload.get("error")))

                vector = _parse_embedding_payload(payload)
                if len(vector) != self._dim:
                    raise ValueError(
                        f"Hugging Face model '{self.model}' returned dimension {len(vector)} "
                        f"but config expects {self._dim}. "
                        "Set HUGGINGFACE_EMBEDDING_DIMENSION to match."
                    )
                embeddings.append(vector)

        logger.info("Hugging Face embeddings generated for %d texts (model=%s)", len(texts), self.model)
        return embeddings
