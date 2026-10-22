from django_app.settings import env

SANDBOX_HOST = env.str("SANDBOX_HOST")
SANDBOX_PORT = env.int("SANDBOX_PORT")
SANDBOX_CLIENT_TIMEOUT = env.float("SANDBOX_CLIENT_TIMEOUT")
