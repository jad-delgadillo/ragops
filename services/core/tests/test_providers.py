"""Unit tests for provider interfaces and configurations."""

import pytest

from services.core.bedrock_provider import BedrockEmbeddingProvider, BedrockLLMProvider
from services.core.config import Settings
from services.core.providers import EmbeddingProvider, LLMProvider


class TestProviderInterfaces:
    """Verify ABCs can't be instantiated directly."""

    def test_embedding_provider_is_abstract(self):
        with pytest.raises(TypeError):
            EmbeddingProvider()  # type: ignore

    def test_llm_provider_is_abstract(self):
        with pytest.raises(TypeError):
            LLMProvider()  # type: ignore

    def test_provider_identity_metadata_from_class_attributes(self):
        class DummyEmbedding(EmbeddingProvider):
            PROVIDER = "dummy"
            MODEL = "embed-1"

            @property
            def dimension(self) -> int:
                return 3

            def embed(self, texts: list[str]) -> list[list[float]]:
                return [[0.0, 0.0, 0.0] for _ in texts]

        provider = DummyEmbedding()
        assert provider.provider_id == "dummy"
        assert provider.model_id == "embed-1"

    def test_provider_identity_metadata_falls_back_to_class_name(self):
        class LocalLLM(LLMProvider):
            def generate(
                self,
                prompt: str,
                *,
                max_tokens: int = 1024,
                temperature: float = 0.1,
            ) -> str:
                return "ok"

        provider = LocalLLM()
        assert provider.provider_id == "local"
        assert provider.model_id == ""


class TestBedrockProviderStubs:
    """Bedrock stubs should raise NotImplementedError."""

    def test_bedrock_embed_not_implemented(self):
        provider = BedrockEmbeddingProvider()
        with pytest.raises(NotImplementedError):
            provider.embed(["test"])

    def test_bedrock_generate_not_implemented(self):
        provider = BedrockLLMProvider()
        with pytest.raises(NotImplementedError):
            provider.generate("test prompt")

    def test_bedrock_dimension(self):
        provider = BedrockEmbeddingProvider()
        assert provider.dimension == 1024


class TestSettings:
    """Verify default settings."""

    def test_defaults(self):
        s = Settings(
            _env_file=None,  # Don't read .env in tests
            OPENAI_API_KEY="test",
        )
        assert s.db_host == "localhost"
        assert s.db_port == 5432
        assert s.db_name == "ragops"
        assert s.embedding_provider == "openai"
        assert s.top_k == 5
        assert s.chunk_size == 512
        assert s.chat_history_turns == 6
        assert s.api_auth_enabled is False
        assert s.api_keys_json == "{}"

    def test_override(self):
        s = Settings(
            _env_file=None,
            DB_HOST="custom-host",
            TOP_K=10,
            OPENAI_API_KEY="test",
        )
        assert s.db_host == "custom-host"
        assert s.top_k == 10
