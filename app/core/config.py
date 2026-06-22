from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="NCP_", extra="ignore")

    app_name: str = "Network Control Platform"
    environment: str = "local"
    database_url: str = "postgresql+psycopg://ncp:ncp@localhost:5432/ncp"
    redis_url: str = "redis://localhost:6379/0"
    secret_key: str | None = Field(default=None, min_length=16)
    default_batch_size: int = 10
    command_timeout_seconds: int = 60
    connect_timeout_seconds: int = 15
    allow_real_device_apply: bool = False
    lab_real_apply_enabled: bool = False
    production_real_apply_enabled: bool = False
    lab_device_allowlist: str = ""
    backup_before_apply: bool = True
    lab_backup_max_age_hours: int = 24
    lab_approval_max_age_hours: int = 24

    @model_validator(mode="after")
    def validate_production_secret_key(self) -> "Settings":
        if self.environment.lower() in {"prod", "production"} and not self.secret_key:
            raise ValueError("NCP_SECRET_KEY is required in production")
        return self

    def encryption_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self.environment.lower() in {"test", "local", "development", "dev"}:
            return "local-test-encryption-key-change-before-production"
        raise ValueError("NCP_SECRET_KEY is required outside test/local environments")


@lru_cache
def get_settings() -> Settings:
    return Settings()
