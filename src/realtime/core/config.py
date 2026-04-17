from pathlib import Path
import sys
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    REALTIME_PORT: int = 8050
    REALTIME_WORKERS: int = 1
    REALTIME_RELOAD: bool = False
    REALTIME_DEBUG_MODE: bool = False

    # --- Redis ---
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str

    # --- Redis Channels (Pub/Sub) ---
    KNOWLEDGE_SEARCH_GET_CHANNEL: str = "knowledge:search:get"
    KNOWLEDGE_SEARCH_RESPONSE_CHANNEL: str = "knowledge:search:response"
    REALTIME_AGENTS_SCHEMA_CHANNEL: str = "realtime_agents:schema"

    # --- Manager Service ---
    MANAGER_HOST: str
    MANAGER_PORT: int

    # --- Django Auth ---
    DJANGO_AUTH_URL: str
    DJANGO_API_KEY: str
    DJANGO_AUTH_TIMEOUT: int = 5

    # --- Database (PostgreSQL) ---
    DB_HOST_NAME: str
    DB_PORT: int = 5432
    DB_NAME: str = "crew"
    DB_REALTIME_USER: str
    DB_REALTIME_PASSWORD: str

    # --- Twilio ---
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    VOICE_AGENT_ID: int = 0
    VOICE_STREAM_URL: str = ""

    # --- Django (for init-realtime HTTP call) ---
    DJANGO_HOST: str = "django_app"
    DJANGO_PORT: int = 8000

    @property
    def INIT_API_URL(self) -> str:
        return f"http://{self.DJANGO_HOST}:{self.DJANGO_PORT}/api/init-realtime/"

    @property
    def DATABASE_URL(self) -> str:
        db_url = (
            f"postgresql+asyncpg://{self.DB_REALTIME_USER}:{self.DB_REALTIME_PASSWORD}@"
            f"{self.DB_HOST_NAME}:{self.DB_PORT}/{self.DB_NAME}"
        )
        return db_url

    model_config = SettingsConfigDict(
        env_file=BASE_DIR.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        # env_prefix="REALTIME_",
    )


@lru_cache
def get_settings():
    is_debug = "--debug" in sys.argv

    env_file = BASE_DIR.parent / ("debug.env" if is_debug else ".env")

    return Settings(
        _env_file=env_file, REALTIME_RELOAD=is_debug, REALTIME_DEBUG_MODE=is_debug
    )


settings = get_settings()
