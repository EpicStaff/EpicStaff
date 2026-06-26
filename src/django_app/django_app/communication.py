from django.conf import settings

from src.shared.communication import Consumer, Producer
from src.shared.communication.brokers import RedisPubSubBroker
from src.shared.communication.storages import RedisStorage


def _redis_url() -> str:
    password = settings.REDIS_PASSWORD
    auth = f":{password}@" if password else ""
    return f"redis://{auth}{settings.REDIS_HOST}:{settings.REDIS_PORT}/0"


_broker = RedisPubSubBroker(_redis_url())
_storage = RedisStorage(_redis_url())

producer = Producer(_broker, _storage)
consumer = Consumer(_broker, _storage)
