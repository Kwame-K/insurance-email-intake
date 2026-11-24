from functools import lru_cache
from pathlib import Path
from typing import Self

from pydantic import SecretStr, model_validator
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

    imap_enabled: bool = False
    imap_host: str = "imap.gmail.com"
    imap_port: int = 993
    imap_user: str = ""
    imap_password: SecretStr = SecretStr("")
    imap_folder: str = "INBOX"
    imap_poll_interval_seconds: float = 30.0
    imap_allowed_senders: str = ""
    imap_max_message_bytes: int = 5_000_000
    imap_max_messages_per_cycle: int = 10
    smtp_reply_enabled: bool = False
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 465
    smtp_timeout_seconds: float = 20.0
    reply_language: str = "en"

    @property
    def allowed_senders(self) -> frozenset[str]:
        return frozenset(
            sender.strip().lower()
            for sender in self.imap_allowed_senders.split(",")
            if sender.strip()
        )

    @model_validator(mode="after")
    def _require_imap_credentials_and_allowlist(self) -> Self:
        if self.imap_enabled and not (
            self.imap_user
            and self.imap_password.get_secret_value()
            and self.allowed_senders
        ):
            raise ValueError(
                "IMAP_ENABLED requires IMAP_USER, IMAP_PASSWORD and "
                "IMAP_ALLOWED_SENDERS (comma-separated)."
            )
        return self

    @model_validator(mode="after")
    def _require_imap_for_replies(self) -> Self:
        if self.smtp_reply_enabled and not self.imap_enabled:
            raise ValueError(
                "SMTP_REPLY_ENABLED requires IMAP_ENABLED, because replies "
                "are sent only to emails received through the mailbox."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
