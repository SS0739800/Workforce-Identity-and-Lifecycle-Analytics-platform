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
    data_dir: Path = PROJECT_ROOT / "data"

    @property
    def raw_data_dir(self) -> Path:
        return self.data_dir / "raw"


@lru_cache
def get_settings() -> Settings:
    return Settings()
