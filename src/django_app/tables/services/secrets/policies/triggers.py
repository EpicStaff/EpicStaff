from tables.services.secrets.policies.base import SecretPolicy

WEBHOOK_TRIGGER_SECRET_POLICY = SecretPolicy(reference_fields=("auth_secret_id",))
NGROK_WEBHOOK_CONFIG_SECRET_POLICY = SecretPolicy(reference_fields=("auth_token_secret_id",))
TELEGRAM_TRIGGER_NODE_SECRET_POLICY = SecretPolicy(
    reference_fields=("telegram_bot_api_key_secret_id",)
)
