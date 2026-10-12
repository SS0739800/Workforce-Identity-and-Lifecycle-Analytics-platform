from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables or a local .env file."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")

    database_url: str
    test_database_url: str | None = None
    log_level: str = "INFO"
    # Read-only login for Power BI (see scripts/create_reporting_user.py)
    reporting_db_user: str = "powerbi_reader"
    reporting_db_password: str | None = None

    # Groq (optional). Without a key the AI endpoints still return the computed data.
    groq_api_key: str | None = None
    # gpt-oss-120b is a Groq production model; the earlier Llama defaults were deprecated in 2026.
    groq_model: str = "openai/gpt-oss-120b"
    groq_timeout_seconds: float = 30.0
    groq_max_retries: int = 2
    groq_max_completion_tokens: int = 2000

    # Gemini (optional) is used when Groq can't answer, e.g. when its token quota runs out.
    gemini_api_key: str | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    gemini_timeout_seconds: float = 30.0
    gemini_max_output_tokens: int = 2000
    data_dir: Path = PROJECT_ROOT / "data"

    @property
    def raw_data_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()
