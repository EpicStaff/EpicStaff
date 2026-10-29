from django_app.settings import env

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "tables.User"

# Each process (every web worker, listen_redis, cache_redis) has its own pool. A thread
# borrows a connection on its first query and returns it when Django closes it: at the
# end of a request, or on close_old_connections(). CONN_MAX_AGE must stay 0, Django
# refuses a pool with persistent connections.
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "USER": env.str("DB_USER"),
        "PASSWORD": env.str("DB_PASSWORD"),
        "HOST": env.str("DB_HOST"),
        "PORT": env.int("DB_PORT"),
        "NAME": env.str("DB_NAME"),
        # The pool checks a connection before lending it, so one Postgres dropped while
        # it sat idle (a restart, a failover) is replaced instead of failing a query.
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "pool": {
                "min_size": env.int("DJANGO_DB_POOL_MIN_SIZE"),
                "max_size": env.int("DJANGO_DB_POOL_MAX_SIZE"),
                "timeout": env.time("DJANGO_DB_POOL_TIMEOUT"),
            },
        },
    }
}
