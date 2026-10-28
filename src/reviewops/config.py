from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "local"
    database_url: SecretStr | None = None
    demo_api_key: SecretStr | None = None
    log_level: str = "INFO"
    build_sha: str = "local"


@lru_cache
def get_settings() -> Settings:
    return Settings()
