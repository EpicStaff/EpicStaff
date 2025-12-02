import os
import sys
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict, Any

IS_DEBUG = "--debug" in sys.argv

config_dict: Dict[str, Any] = {
    'env_file_encoding': 'utf-8',
    'extra': 'ignore'
}

if IS_DEBUG:
    env_file_path = "../debug.env"
    print(f"--- DEBUG MODE: Loading settings from {env_file_path} ---")
    config_dict['env_file'] = env_file_path
else:
    print("--- STANDARD MODE: Loading settings from system environment ---")


class Settings(BaseSettings):

    USE_TUNNEL: bool = False
    WEBHOOK_TUNNEL: Optional[str] = None
    WEBHOOK_AUTH: Optional[str] = None
    WEBHOOK_PORT: int = 8009
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    
    model_config = SettingsConfigDict(**config_dict)

    @model_validator(mode='after')
    def check_tunnel_config(self) -> 'Settings':

        if self.USE_TUNNEL:
            if not self.WEBHOOK_TUNNEL:
                raise ValueError(
                    "Configuration error: USE_TUNNEL is True, "
                    "but WEBHOOK_TUNNEL is not set."
                )
            if not self.WEBHOOK_AUTH:
                raise ValueError(
                    f"Configuration error for provider '{self.WEBHOOK_TUNNEL}': "
                    "USE_TUNNEL is True, but WEBHOOK_AUTH (the auth token) is not set."
                )
        return self


try:
    settings = Settings()
except (ValueError, FileNotFoundError) as e:
    print(f"\nFATAL CONFIGURATION ERROR:\n{e}", file=sys.stderr)
    sys.exit(1)

