from pathlib import Path
from typing import Annotated

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[3]

CommaList = Annotated[list[str], NoDecode]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    test_database_url: str | None = None
    gemini_api_key: SecretStr | None = None
    gemini_model: str = "gemini-3.5-flash-lite"
    # Free-tier limit for gemini-3.5-flash-lite as reported by the API on 2026-11-12.
    gemini_requests_per_minute: int = Field(default=15, ge=1)

    # Ingestion. Lists are comma-separated in the environment.
    ingest_sources: CommaList = []
    greenhouse_boards: CommaList = []
    lever_companies: CommaList = []
    himalayas_api_key: SecretStr | None = None

    @field_validator(
        "ingest_sources",
        "greenhouse_boards",
        "lever_companies",
        "extraction_excluded_sources",
        mode="before",
    )
    @classmethod
    def _split_comma_list(cls, value: object) -> object:
        # Board tokens and company slugs are used as given, so case is preserved.
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    # Extraction cost guards and data-use rules.
    extraction_batch_limit: int = Field(default=50, ge=1)
    extraction_max_description_chars: int = Field(default=12000, ge=500)
    extraction_max_attempts: int = Field(default=3, ge=1)
    # Remote OK reserves AI training on its data; on the Gemini free tier, API inputs may be
    # used to improve Google's models, so Remote OK postings are not sent by default.
    extraction_excluded_sources: CommaList = ["remoteok"]

    @field_validator("himalayas_api_key", "gemini_api_key", mode="before")
    @classmethod
    def _blank_secret_is_none(cls, value: object) -> object:
        # An unset GitHub Actions secret arrives as an empty string.
        if isinstance(value, str) and not value.strip():
            return None
        return value


settings = Settings()
