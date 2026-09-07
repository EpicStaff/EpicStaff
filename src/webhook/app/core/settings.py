import sys

from src.shared.envtools import Env

env = Env()

IS_DEBUG = "--debug" in sys.argv

if IS_DEBUG:
    env_file_path = "../.debug.env"
    print(f"--- DEBUG MODE: Loading settings from {env_file_path} ---")
    try:
        env.read_env(env_file_path)
    except (ValueError, TypeError) as e:
        print(f"\nFATAL CONFIGURATION ERROR:\n{e}", file=sys.stderr)
        sys.exit(1)
else:
    print("--- STANDARD MODE: Loading settings from system environment ---")


class Settings:
    # --- Tunnel ---
    WEBHOOK_TUNNEL: str | None = env.str("WEBHOOK_TUNNEL", None)
    NGROK_DOMAIN: str | None = env.str("WEBHOOK_NGROK_DOMAIN", None)

    # --- Server ---
    WEBHOOK_PORT: int = env.int("WEBHOOK_PORT")
    LOG_LEVEL: str = env.str("WEBHOOK_LOG_LEVEL")

    # --- Redis ---
    REDIS_HOST: str = env.str("REDIS_HOST")
    REDIS_PORT: int = env.int("REDIS_PORT")
    REDIS_USER: str = env.str("REDIS_USER")
    REDIS_PASSWORD: str = env.str("REDIS_PASSWORD")

    # --- Channels ---
    REDIS_TUNNEL_CONFIG_CHANNEL: str = env.str("REDIS_TUNNEL_CONFIG_CHANNEL", "REDIS_TUNNEL_CONFIG_CHANNEL")
    REQUEST_WEBHOOK_UPDATE_CHANNEL: str = env.str("REQUEST_WEBHOOK_UPDATE_CHANNEL", "REQUEST_WEBHOOK_UPDATE_CHANNEL")
    WEBHOOK_MESSAGE_CHANNEL: str = env.str("WEBHOOK_MESSAGE_CHANNEL", "webhooks")

    # --- Tunnel behaviour ---
    WEBHOOK_TUNNEL_RECONNECT_TIMEOUT: int = env.int("WEBHOOK_TUNNEL_RECONNECT_TIMEOUT", 10)
    TUNNEL_URLS_HASH_KEY: str = env.str("TUNNEL_URLS_HASH_KEY", "tunnel_urls")

    # --- Upstream targets ---
    REALTIME_URL: str = env.str("REALTIME_URL", "http://realtime:8050")
    NGROK_TARGET_HOST: str = env.str("NGROK_TARGET_HOST", "epicstaff-nginx")
    NGROK_TARGET_PORT: int = env.int("NGROK_TARGET_PORT", 80)
    LOCALHOST_TARGET_HOST: str = env.str("LOCALHOST_TARGET_HOST", "localhost")
    LOCALHOST_TARGET_PORT: int = env.int("LOCALHOST_TARGET_PORT", 8009)

    # --- CORS (env key is DJANGO_CORS_ALLOWED_ORIGINS, matching the BaseSettings alias) ---
    CORS_ALLOWED_ORIGINS: str = env.str("DJANGO_CORS_ALLOWED_ORIGINS")

    # --- Soft config list (optional — default empty string preserves original behaviour) ---
    WEBHOOK_EMPTY_JSON_PATHS: str = env.str("WEBHOOK_EMPTY_JSON_PATHS", "")

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ALLOWED_ORIGINS.split(",") if origin.strip()]

    @property
    def webhook_empty_json_paths_set(self) -> set[str]:
        return {p.strip() for p in self.WEBHOOK_EMPTY_JSON_PATHS.split(",") if p.strip()}


try:
    settings = Settings()
except Exception as e:
    print(f"\nFATAL CONFIGURATION ERROR:\n{e}", file=sys.stderr)
    sys.exit(1)
