from src.shared.communication import Consumer, Producer
from src.shared.communication.brokers import RedisPubSubBroker
from src.shared.communication.storages import RedisStorage
from shared.communication.dns import redis_url

_broker = RedisPubSubBroker(redis_url("DJANGO_BROKER", "redis"))
_storage = RedisStorage(redis_url("DJANGO_STORAGE", "redis"))

producer = Producer(_broker, _storage)
consumer = Consumer(_broker, _storage)
