"""AWS Bedrock provider stubs — placeholder for v2 enterprise option."""

from services.core.providers import EmbeddingProvider, LLMProvider


class BedrockEmbeddingProvider(EmbeddingProvider):
    """AWS Bedrock Titan Embeddings v2 — stub for future implementation."""

    PROVIDER = "bedrock"
    MODEL = "amazon.titan-embed-text-v2:0"
    DIMENSION = 1024  # Titan Embeddings v2 default

    def __init__(self, region: str = "us-east-1"):
        self._region = region

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(
            "Bedrock embedding provider is a v2 feature. Use OpenAI provider for MVP."
        )


class BedrockLLMProvider(LLMProvider):
    """AWS Bedrock text model — stub for future implementation."""

    PROVIDER = "bedrock"

    def __init__(
        self,
        region: str = "us-east-1",
        model_id: str = "anthropic.claude-3-haiku-20240307-v1:0",
    ):
        self._region = region
        self._model_id = model_id

    def generate(
        self,
        prompt: str,
        *,
        max_tokens: int = 1024,
        temperature: float = 0.1,
    ) -> str:
        raise NotImplementedError(
            "Bedrock LLM provider is a v2 feature. Use OpenAI provider for MVP."
        )
