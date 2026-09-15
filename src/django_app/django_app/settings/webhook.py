from django_app.settings import env

WEBHOOK_HOST = env.str("WEBHOOK_HOST")
WEBHOOK_PORT = env.int("WEBHOOK_PORT")
WEBHOOK_USE_TUNNEL = env.bool("WEBHOOK_USE_TUNNEL")
WEBHOOK_TUNNEL = env.str("WEBHOOK_TUNNEL")
