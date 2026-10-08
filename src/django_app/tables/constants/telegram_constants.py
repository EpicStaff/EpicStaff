from enum import StrEnum


class TelegramRegistrationBlockerCode(StrEnum):
    """Why registering a node's webhook with Telegram cannot work. Values are an API contract."""

    NO_BOT_KEY = "no_bot_key"
    NO_WEBHOOK_TRIGGER = "no_webhook_trigger"
    NO_TUNNEL_PROVIDER = "no_tunnel_provider"
    LOCALHOST_PROVIDER = "localhost_provider"
    AUTH_KIND_CONFLICT = "auth_kind_conflict"
    NO_TELEGRAM_SECRET = "no_telegram_secret"
    INVALID_TELEGRAM_SECRET = "invalid_telegram_secret"
    UNRESOLVABLE_TELEGRAM_SECRET = "unresolvable_telegram_secret"
