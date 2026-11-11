from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: SecretStr | None = None
    demo_api_key: SecretStr | None = None
    log_level: str = "INFO"
    build_sha: str = "local"
    moonshot_api_key: SecretStr | None = None
    kimi_model: str = Field(default="kimi-k2.6", min_length=1, max_length=100)
    kimi_timeout_seconds: int = Field(default=60, ge=5, le=120)


@lru_cache
def get_settings() -> Settings:
    return Settings()
