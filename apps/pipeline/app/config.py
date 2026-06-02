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

    # Optional dev bypass. When unset, the workspace `llm_cohere` key from Postgres is used.
    cohere_api_key: str | None = Field(default=None, validation_alias="COHERE_API_KEY")

    # Slack OAuth app credentials (one app serves all workspaces; per-workspace
    # access tokens are stored encrypted in api_keys). Unset until a Slack app
    # is configured for the deployment.
    slack_client_id: str | None = Field(default=None, validation_alias="SLACK_CLIENT_ID")
    slack_client_secret: str | None = Field(
        default=None, validation_alias="SLACK_CLIENT_SECRET"
    )
    slack_redirect_uri: str | None = Field(
        default=None, validation_alias="SLACK_REDIRECT_URI"
    )

    zkast_otel_enabled: bool = False
    graphiti_telemetry_enabled: bool = False

    pipeline_version: str = "0.0.1"
    api_contract_version: str = "v1"

    zkast_storage_root: str = Field(
        default="/var/zkast/storage",
        validation_alias="ZKAST_STORAGE_ROOT",
    )
    max_upload_bytes: int = Field(
        default=50 * 1024 * 1024,
        validation_alias="MAX_UPLOAD_BYTES",
    )

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
