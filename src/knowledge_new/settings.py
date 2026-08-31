from pathlib import Path

from loguru import logger
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict
from src.shared.communication.dns import build_dns

__all__ = ["settings"]


class MainSettings(BaseSettings):
    BASE_DIR: Path = Path(__file__).resolve().parent

    DEBUG: bool = False

    MAX_PROCESS_WORKERS: int = 10

    DATABASE_BACKEND: str = "postgresql+psycopg"
    DATABASE_USER: str = ""
    DATABASE_PASSWORD: str = ""
    DATABASE_HOST: str
    DATABASE_PORT: int
    DATABASE_NAME: str

    BROKER_BACKEND: str = "redis"
    BROKER_USER: str = Field(default="", validation_alias="COMMUNICATION_BROKER_USER")
    BROKER_PASSWORD: str = Field(default="", validation_alias="COMMUNICATION_BROKER_PASSWORD")
    BROKER_HOST: str = Field(validation_alias="COMMUNICATION_BROKER_HOST")
    BROKER_PORT: int = Field(validation_alias="COMMUNICATION_BROKER_PORT")
    BROKER_NAME: str = Field(validation_alias="COMMUNICATION_BROKER_NAME")

    STORAGE_BACKEND: str = "redis"
    STORAGE_USER: str = Field(default="", validation_alias="COMMUNICATION_STORAGE_USER")
    STORAGE_PASSWORD: str = Field(default="", validation_alias="COMMUNICATION_STORAGE_PASSWORD")
    STORAGE_HOST: str = Field(validation_alias="COMMUNICATION_STORAGE_HOST")
    STORAGE_PORT: int = Field(validation_alias="COMMUNICATION_STORAGE_PORT")
    STORAGE_NAME: str = Field(validation_alias="COMMUNICATION_STORAGE_NAME")

    SEARCH_REQUEST_CHANNEL: str
    SEARCH_RESPONSE_CHANNEL: str
    PRECHUNK_REQUEST_CHANNEL: str
    PRECHUNK_RESPONSE_CHANNEL: str
    INDEX_REQUEST_CHANNEL: str
    CANCEL_REQUEST_CHANNEL: str

    MINIO_HOST: str = "http://minio:9000"
    MINIO_ACCESS_KEY: str = "minioadmin"
    MINIO_SECRET_KEY: str = "minioadmin_secret"
    MINIO_BUCKET: str = "knowledge"

    GRAPHRAG_ENCODING: str = "utf-8"

    model_config = SettingsConfigDict(
        env_file=BASE_DIR / "../.env",
        env_prefix="KNOWLEDGE_",
        extra="ignore",
    )

    @computed_field
    def DATABASE_DNS(self) -> str:  # noqa: N802
        return build_dns(
            self.DATABASE_BACKEND,
            self.DATABASE_HOST,
            self.DATABASE_PORT,
            self.DATABASE_NAME,
            self.DATABASE_USER,
            self.DATABASE_PASSWORD,
        )

    @computed_field
    def BROKER_DNS(self) -> str:  # noqa: N802
        return build_dns(
            self.BROKER_BACKEND,
            self.BROKER_HOST,
            self.BROKER_PORT,
            self.BROKER_NAME,
            self.BROKER_USER,
            self.BROKER_PASSWORD,
        )

    @computed_field
    def STORAGE_DNS(self) -> str:  # noqa: N802
        return build_dns(
            self.STORAGE_BACKEND,
            self.STORAGE_HOST,
            self.STORAGE_PORT,
            self.STORAGE_NAME,
            self.STORAGE_USER,
            self.STORAGE_PASSWORD,
        )


settings = MainSettings()

logger.debug("Settings:\n{}", settings)
