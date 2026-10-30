from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bot_token: str = Field(alias="BOT_TOKEN")
    allowed_chat_id: int = Field(alias="ALLOWED_CHAT_ID")
    admin_telegram_id: int = Field(alias="ADMIN_TELEGRAM_ID")

    timezone: str = Field(default="Asia/Sakhalin", alias="TIMEZONE")
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")

    spreadsheet_id: str = Field(alias="SPREADSHEET_ID")
    sheets_registry_tab: str = Field(default="Лист1", alias="SHEETS_REGISTRY_TAB")
    sheets_exceptions_tab: str = Field(default="Исключения", alias="SHEETS_EXCEPTIONS_TAB")

    gmail_credentials_file: Path = Field(
        default=Path("data/gmail_credentials.json"),
        alias="GMAIL_CREDENTIALS_FILE",
    )
    gmail_token_file: Path = Field(
        default=Path("data/gmail_token.json"),
        alias="GMAIL_TOKEN_FILE",
    )
    gmail_user: str = Field(
        default="theofficesakh@gmail.com", alias="GMAIL_USER"
    )
    invoice_to_email: str = Field(
        default="invoice@docsinbox.ru", alias="INVOICE_TO_EMAIL"
    )
    mail_subject_prefix: str = Field(
        default="ООО Сфофрендз инн 6501291591",
        alias="MAIL_SUBJECT_PREFIX",
    )
    mail_body: str = Field(default="Внести", alias="MAIL_BODY")

    album_debounce_seconds: float = Field(default=1.5, alias="ALBUM_DEBOUNCE_SECONDS")
    max_attachment_bytes: int = Field(
        default=20 * 1024 * 1024, alias="MAX_ATTACHMENT_BYTES"
    )
    gmail_poll_interval_seconds: int = Field(
        default=60, alias="GMAIL_POLL_INTERVAL_SECONDS"
    )
    resend_after_hours: int = Field(default=48, alias="RESEND_AFTER_HOURS")
    max_send_attempts: int = Field(default=3, alias="MAX_SEND_ATTEMPTS")
    health_stale_minutes: int = Field(default=20, alias="HEALTH_STALE_MINUTES")
    sheets_sync_interval_seconds: int = Field(
        default=120, alias="SHEETS_SYNC_INTERVAL_SECONDS"
    )
    exceptions_cache_ttl_seconds: int = Field(
        default=60, alias="EXCEPTIONS_CACHE_TTL_SECONDS"
    )
    admin_alert_cooldown_seconds: int = Field(
        default=1800, alias="ADMIN_ALERT_COOLDOWN_SECONDS"
    )
    gmail_auth_alert_cooldown_seconds: int = Field(
        default=21600, alias="GMAIL_AUTH_ALERT_COOLDOWN_SECONDS"
    )

    @property
    def database_path(self) -> Path:
        return self.data_dir / "docofficebot.db"

    @property
    def claims_dir(self) -> Path:
        return self.data_dir / "claims"

    @property
    def backups_dir(self) -> Path:
        return self.data_dir / "backups"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
