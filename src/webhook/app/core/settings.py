import sys
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict, Any

IS_DEBUG = "--debug" in sys.argv

config_dict: Dict[str, Any] = {"env_file_encoding": "utf-8", "extra": "ignore"}

if IS_DEBUG:
    env_file_path = "../debug.env"
    print(f"--- DEBUG MODE: Loading settings from {env_file_path} ---")
    config_dict["env_file"] = env_file_path
else:
    print("--- STANDARD MODE: Loading settings from system environment ---")


class Settings(BaseSettings):
    WEBHOOK_TUNNEL: Optional[str] = None
    WEBHOOK_AUTH: Optional[str] = None
    NGROK_DOMAIN: Optional[str] = None
    WEBHOOK_PORT: int = 8009
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = "redis_password"
    REDIS_TUNNEL_CONFIG_CHANNEL: str = "REDIS_TUNNEL_CONFIG_CHANNEL"
    REQUEST_WEBHOOK_UPDATE_CHANNEL: str = "REQUEST_WEBHOOK_UPDATE_CHANNEL"
    WEBHOOK_TUNNEL_RECONNECT_TIMEOUT: int = 10
    LOG_LEVEL: str = "INFO"
    TUNNEL_URLS_HASH_KEY: str = "tunnel_urls"

    model_config = SettingsConfigDict(**config_dict)


try:
    settings = Settings()
except (ValueError, FileNotFoundError) as e:
    print(f"\nFATAL CONFIGURATION ERROR:\n{e}", file=sys.stderr)
    sys.exit(1)
