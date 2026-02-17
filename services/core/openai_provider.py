"""OpenAI embedding and LLM provider implementations."""

import logging

from openai import OpenAI

from services.core.providers import EmbeddingProvider, LLMProvider

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI text-embedding-3-small provider."""

    MODEL = "text-embedding-3-small"
    DIMENSION = 1536
    MAX_BATCH = 2048  # OpenAI limit per request

    def __init__(self, api_key: str | None = None):
        self._client = OpenAI(api_key=api_key)  # reads OPENAI_API_KEY env if None

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts in batches respecting API limits."""
        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), self.MAX_BATCH):
            batch = texts[i : i + self.MAX_BATCH]
            logger.info("Embedding batch %d–%d (%d texts)", i, i + len(batch), len(batch))
            response = self._client.embeddings.create(model=self.MODEL, input=batch)
            all_embeddings.extend([item.embedding for item in response.data])
        return all_embeddings


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------


class OpenAILLMProvider(LLMProvider):
    """OpenAI GPT-4o-mini LLM provider."""

    MODEL = "gpt-4o-mini"

    def __init__(self, api_key: str | None = None):
        self._client = OpenAI(api_key=api_key)

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        logger.info("Generating response (max_tokens=%d, temp=%.2f)", max_tokens, temperature)
        response = self._client.chat.completions.create(
            model=self.MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
