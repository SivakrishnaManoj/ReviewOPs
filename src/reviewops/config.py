from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: SecretStr | None = None
    demo_api_key: SecretStr | None = None
    log_level: str = "INFO"
    build_sha: str = "local"
    llm_provider: Literal["gemini", "moonshot"] = "gemini"
    gemini_api_key: SecretStr | None = None
    gemini_model: str = Field(
        default="gemini-3.8-flash",
        min_length=1,
        max_length=100,
        pattern=r"^gemini-[a-zA-Z0-9.-]+$",
    )
    gemini_timeout_seconds: int = Field(default=60, ge=5, le=120)
    moonshot_api_key: SecretStr | None = None
    kimi_model: str = Field(default="kimi-k3.1-pro", min_length=1, max_length=100)
    kimi_timeout_seconds: int = Field(default=60, ge=5, le=120)


@lru_cache
def get_settings() -> Settings:
    return Settings()
