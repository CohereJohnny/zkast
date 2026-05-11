"""Application configuration."""

from __future__ import annotations

import base64

from pydantic import Field, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str
    redis_url: str
    falkordb_host: str
    falkordb_port: int = 6379
    internal_pipeline_token: str
    master_encryption_key: str = Field(
        ...,
        description="Base64-encoded 32-byte AES key",
    )

    zkast_otel_enabled: bool = False
    graphiti_telemetry_enabled: bool = False

    pipeline_version: str = "0.0.1"
    api_contract_version: str = "v1"

    @field_validator("master_encryption_key")
    @classmethod
    def validate_master_key_b64(cls, value: str) -> str:
        raw = base64.b64decode(value)
        if len(raw) != 32:
            raise ValueError("MASTER_ENCRYPTION_KEY must decode to exactly 32 bytes")
        return value

    @computed_field  # type: ignore[prop-decorator]
    @property
    def master_encryption_key_bytes(self) -> bytes:
        return base64.b64decode(self.master_encryption_key)


def get_settings() -> Settings:
    return Settings()
