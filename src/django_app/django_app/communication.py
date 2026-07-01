import os

from src.shared.communication import Consumer, Producer
from src.shared.communication.brokers import RedisPubSubBroker
from src.shared.communication.storages import RedisStorage


def _build_dns(provider: str, host: str, port: int, db: str, user="", password=""):
    user_part = f"{user}:{password}@" if user or password else ""
    return f"{provider}://{user_part}{host}:{port}/{db}"


def _redis_url(prefix: str) -> str:
    return _build_dns(
        "redis",
        host=os.environ[f"{prefix}_HOST"],
        port=os.environ[f"{prefix}_PORT"],
        db=os.environ[f"{prefix}_DB"],
        user=os.environ.get(f"{prefix}_USER", ""),
        password=os.environ.get(f"{prefix}_PASSWORD", ""),
    )


_broker = RedisPubSubBroker(_redis_url("DJANGO_BROKER"))
_storage = RedisStorage(_redis_url("DJANGO_STORAGE"))

producer = Producer(_broker, _storage)
consumer = Consumer(_broker, _storage)
