"""Provider-agnostic interfaces for embedding and LLM services."""

from abc import ABC, abstractmethod
from typing import Any


def _derive_provider_id_from_class_name(class_name: str) -> str:
    lowered = class_name.strip().lower()
    for suffix in (
        "embeddingprovider",
        "llmprovider",
        "provider",
        "embedding",
        "llm",
    ):
        if lowered.endswith(suffix):
            lowered = lowered[: -len(suffix)]
            break
    return lowered or "unknown"


class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers."""

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts into vectors.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (list of floats).
        """

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Return the dimensionality of the embedding vectors."""

    @property
    def provider_id(self) -> str:
        """Stable provider identifier used in metadata and diagnostics."""
        explicit = getattr(self, "PROVIDER", "")
        if explicit:
            return str(explicit).strip().lower()
        return _derive_provider_id_from_class_name(self.__class__.__name__)

    @property
    def model_id(self) -> str:
        """Model identifier when the provider exposes one."""
        model = (
            getattr(self, "MODEL", None)
            or getattr(self, "model", None)
            or getattr(self, "_model_id", None)
        )
        return str(model or "").strip()


class LLMProvider(ABC):
    """Abstract interface for LLM providers."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        """Generate a response from the LLM."""

    @property
    def provider_id(self) -> str:
        """Stable provider identifier used in metadata and diagnostics."""
        explicit = getattr(self, "PROVIDER", "")
        if explicit:
            return str(explicit).strip().lower()
        return _derive_provider_id_from_class_name(self.__class__.__name__)

    @property
    def model_id(self) -> str:
        """Model identifier when the provider exposes one."""
        model = (
            getattr(self, "MODEL", None)
            or getattr(self, "model", None)
            or getattr(self, "_model_id", None)
        )
        return str(model or "").strip()


def get_embedding_provider(settings: Any) -> EmbeddingProvider:
    """Factory to get the configured embedding provider.

    Supported values for EMBEDDING_PROVIDER:
        openai (default), gemini, huggingface, ollama
    """
    provider = settings.embedding_provider.lower()

    if provider == "ollama":
        from services.core.ollama_provider import OllamaEmbeddingProvider

        return OllamaEmbeddingProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_embedding_model,
        )

    if provider == "gemini":
        from services.core.gemini_provider import GeminiEmbeddingProvider

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini")
        return GeminiEmbeddingProvider(api_key=settings.gemini_api_key)

    if provider in {"huggingface", "hf"}:
        from services.core.huggingface_provider import HuggingFaceEmbeddingProvider

        if not settings.huggingface_api_key:
            raise ValueError("HUGGINGFACE_API_KEY is required when EMBEDDING_PROVIDER=huggingface")
        return HuggingFaceEmbeddingProvider(
            api_key=settings.huggingface_api_key,
            model=settings.huggingface_embedding_model,
            base_url=settings.huggingface_base_url,
            dimension=settings.huggingface_embedding_dimension,
        )

    # Default: openai
    from services.core.openai_provider import OpenAIEmbeddingProvider

    return OpenAIEmbeddingProvider(api_key=settings.openai_api_key or None)


def get_llm_provider(settings: Any) -> LLMProvider | None:
    """Factory to get the configured LLM provider.

    Supported values for LLM_PROVIDER:
        openai (default), gemini, claude, groq, ollama
    """
    if not settings.llm_enabled:
        return None

    provider = settings.llm_provider.lower()

    if provider == "ollama":
        from services.core.ollama_provider import OllamaLLMProvider

        return OllamaLLMProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_llm_model,
        )

    if provider == "gemini":
        from services.core.gemini_provider import GeminiLLMProvider

        if not settings.gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        return GeminiLLMProvider(api_key=settings.gemini_api_key)

    if provider == "claude" or provider == "anthropic":
        from services.core.claude_provider import ClaudeLLMProvider

        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude")
        return ClaudeLLMProvider(api_key=settings.anthropic_api_key)

    if provider == "groq":
        from services.core.groq_provider import GroqLLMProvider

        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return GroqLLMProvider(api_key=settings.groq_api_key)

    # Default: openai
    from services.core.openai_provider import OpenAILLMProvider

    return OpenAILLMProvider(api_key=settings.openai_api_key or None)
