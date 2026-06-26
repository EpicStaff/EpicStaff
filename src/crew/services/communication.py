import os

from src.shared.communication import Consumer, Producer
from src.shared.communication.brokers import RedisPubSubBroker
from src.shared.communication.storages import RedisStorage


def _redis_url() -> str:
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6379")
    password = os.environ.get("REDIS_PASSWORD")
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{host}:{port}/0"


_broker = RedisPubSubBroker(_redis_url())
_storage = RedisStorage(_redis_url())

producer = Producer(_broker, _storage)
consumer = Consumer(_broker, _storage)
