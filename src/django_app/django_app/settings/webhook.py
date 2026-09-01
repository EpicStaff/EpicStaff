from django_app.settings import env

WEBHOOK_USE_TUNNEL = env.bool("WEBHOOK_USE_TUNNEL", False)
WEBHOOK_TUNNEL = env.str("WEBHOOK_TUNNEL", "")
WEBHOOK_HOST_NAME = env.str("WEBHOOK_HOST_NAME", "localhost")
WEBHOOK_PORT = env.int("WEBHOOK_PORT", 8009)