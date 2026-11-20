from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    underwriting_base_url: str = "http://127.0.0.1:8002"
    underwriting_timeout_seconds: float = 120.0
    inbox_dir: Path = Path("data/inbox")
    state_dir: Path = Path("data/state")
    persist_decisions: bool = True
    watch_enabled: bool = False
    watch_interval_seconds: float = 10.0
    default_language: str = "en"


@lru_cache
def get_settings() -> Settings:
    return Settings()
