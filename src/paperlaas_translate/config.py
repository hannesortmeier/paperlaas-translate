from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = Field(default="0.0.0.0")
    app_port: int = Field(default=8000)
    log_level: str = Field(default="INFO")

    paperless_token: str
    paperless_verify_ssl: bool = Field(default=False)
    paperless_timeout_seconds: float = Field(default=60.0)
    paperless_task_poll_seconds: float = Field(default=2.0)
    paperless_task_timeout_seconds: float = Field(default=300.0)

    openai_api_key: str
    openai_base_url: str
    openai_model: str

    translation_batch_chars: int = Field(default=4000, ge=500)
    translation_batch_items: int = Field(default=12, ge=1)

    pdf2zh_command: str = Field(default="pdf2zh_next")
    pdf2zh_source_language: str | None = Field(default=None)
    pdf2zh_watermark_output_mode: Literal["watermarked", "no_watermark", "both"] = Field(
        default="no_watermark"
    )
    pdf2zh_timeout_seconds: float = Field(default=1800.0)
    temp_dir: str = Field(default="/tmp/paperlaas-translate")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
