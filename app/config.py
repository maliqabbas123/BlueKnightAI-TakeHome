from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://blueknight:blueknight@localhost:5432/blueknight"
    jwt_secret: str = "dev-secret"
    jwt_algorithm: str = "HS256"
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_prefix="")


@lru_cache
def get_settings() -> Settings:
    return Settings()

