"""Application settings loaded from environment variables."""

import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration for the backend.

    Every value has a safe default and can be overridden through an
    environment variable matching the field name (case-insensitive).
    """

    model_config = SettingsConfigDict(extra="ignore")

    llm_base_url: str = "https://api.deepseek.com"
    llm_model: str = "deepseek-v4-flash"
    llm_api_key_env: str = "LLM_API_KEY"
    analysis_concurrency: int = 4
    max_files: int = 50
    max_diff_bytes: int = 2 * 1024 * 1024
    file_token_budget_in: int = 8000
    file_token_budget_out: int = 4000
    llm_timeout_sec: float = 60.0
    example_pr: str = "owner/repo/pull/1"
    database_path: str = "data/analyses.db"
    rate_limit_per_min: int = 10

    def api_key(self) -> str | None:
        """Return the LLM API key from the configured environment variable.

        Keyring-backed lookup lands in T11; for now the environment value
        (e.g. ``LLM_API_KEY``) is returned directly.
        """
        return os.getenv(self.llm_api_key_env)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached ``Settings`` instance."""
    return Settings()
