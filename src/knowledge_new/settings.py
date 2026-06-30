from pathlib import Path

from loguru import logger
from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

__all__ = ["settings"]


def _build_dns(provider: str, host: str, port: int, db: str, user="", password=""):
    user_part = f"{user}:{password}@" if user or password else ""
    return f"{provider}://{user_part}{host}:{port}/{db}"


class MainSettings(BaseSettings):
    BASE_DIR: Path = Path(__file__).resolve().parent

    DEBUG: bool = False

    MAX_PROCESS_WORKERS: int = 10

    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_HOST: str
    POSTGRES_PORT: int
    POSTGRES_DB: str

    BROKER_BACKEND: str = "redis"
    BROKER_USER: str = ""
    BROKER_PASSWORD: str = ""
    BROKER_HOST: str
    BROKER_PORT: int
    BROKER_DB: str

    STORAGE_BACKEND: str = "redis"
    STORAGE_USER: str = ""
    STORAGE_PASSWORD: str = ""
    STORAGE_HOST: str
    STORAGE_PORT: int
    STORAGE_DB: str

    SEARCH_REQUEST_CHANNEL: str = "knowledge:search:get"
    SEARCH_RESPONSE_CHANNEL: str = "knowledge:search:response"

    PRECHUNK_REQUEST_CHANNEL: str = "knowledge:chunk"
    PRECHUNK_RESPONSE_CHANNEL: str = "knowledge:chunk:response"

    INDEX_REQUEST_CHANNEL: str = "knowledge:indexing"

    CANCEL_REQUEST_CHANNEL: str = "knowledge:cancel:request"

    model_config = SettingsConfigDict(env_file=BASE_DIR / "../.env", env_prefix="KNOWLEDGE_")

    @computed_field
    def POSTGRES_DNS(self) -> str:  # noqa: N802
        return _build_dns(
            "postgresql+psycopg",
            self.POSTGRES_HOST,
            self.POSTGRES_PORT,
            self.POSTGRES_DB,
            self.POSTGRES_USER,
            self.POSTGRES_PASSWORD,
        )

    @computed_field
    def BROKER_DNS(self) -> str:  # noqa: N802
        return _build_dns(
            self.BROKER_BACKEND,
            self.BROKER_HOST,
            self.BROKER_PORT,
            self.BROKER_DB,
            self.BROKER_USER,
            self.BROKER_PASSWORD,
        )

    @computed_field
    def STORAGE_DNS(self) -> str:  # noqa: N802
        return _build_dns(
            self.STORAGE_BACKEND,
            self.STORAGE_HOST,
            self.STORAGE_PORT,
            self.STORAGE_DB,
            self.STORAGE_USER,
            self.STORAGE_PASSWORD,
        )


settings = MainSettings()

logger.debug("Settings:\n{}", settings)
