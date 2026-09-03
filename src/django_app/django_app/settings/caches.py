from django_app.settings import REDIS_HOST, REDIS_USER, REDIS_PASSWORD, REDIS_PORT


CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": f"redis://{REDIS_HOST}:{REDIS_PORT}/1",
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "SERIALIZER": "django_redis.serializers.json.JSONSerializer",
            "USER": REDIS_USER,
            "PASSWORD": REDIS_PASSWORD,
        },
    }
}
