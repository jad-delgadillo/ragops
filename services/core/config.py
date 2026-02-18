"""Application configuration loaded from environment variables."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration — reads from env vars / .env file."""

    # --- Database ---
    database_url: str | None = Field(default=None, alias="DATABASE_URL")
    neon_connection_string: str | None = Field(default=None, alias="NEON_CONNECTION_STRING")
    db_host: str = Field(default="localhost", alias="DB_HOST")
    db_port: int = Field(default=5432, alias="DB_PORT")
    db_name: str = Field(default="ragops", alias="DB_NAME")
    db_user: str = Field(default="ragops", alias="DB_USER")
    db_password: str = Field(default="ragops", alias="DB_PASSWORD")

    # --- Embedding provider ---
    embedding_provider: str = Field(default="openai", alias="EMBEDDING_PROVIDER")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    # --- LLM provider ---
    llm_provider: str = Field(default="openai", alias="LLM_PROVIDER")
    llm_enabled: bool = Field(default=False, alias="LLM_ENABLED")

    # --- Provider API keys ---
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    groq_api_key: str = Field(default="", alias="GROQ_API_KEY")
    github_token: str = Field(default="", alias="GITHUB_TOKEN")

    # --- Ollama (Local LLM) ---
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    ollama_embedding_model: str = Field(
        default="mxbai-embed-large", alias="OLLAMA_EMBEDDING_MODEL"
    )
    ollama_llm_model: str = Field(default="llama3", alias="OLLAMA_LLM_MODEL")



    # --- Retrieval ---
    top_k: int = Field(default=5, alias="TOP_K")
    chunk_size: int = Field(default=512, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=64, alias="CHUNK_OVERLAP")
    chat_history_turns: int = Field(default=6, alias="CHAT_HISTORY_TURNS")

    # --- S3 (for AWS deploys) ---
    s3_bucket: str = Field(default="", alias="S3_BUCKET")
    aws_region: str = Field(default="us-east-1", alias="AWS_REGION")

    # --- App ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    environment: str = Field(default="local", alias="ENVIRONMENT")
    repo_onboarding_enabled: bool = Field(default=False, alias="REPO_ONBOARDING_ENABLED")
    repo_cache_dir: str = Field(default="", alias="REPO_CACHE_DIR")
    repo_manuals_dir: str = Field(default="", alias="REPO_MANUALS_DIR")
    repo_archive_max_mb: int = Field(default=80, alias="REPO_ARCHIVE_MAX_MB")
    repo_onboarding_timeout_seconds: int = Field(
        default=60,
        alias="REPO_ONBOARDING_TIMEOUT_SECONDS",
    )

    # --- Access control ---
    api_auth_enabled: bool = Field(default=False, alias="API_AUTH_ENABLED")
    api_keys_json: str = Field(default="{}", alias="API_KEYS_JSON")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
