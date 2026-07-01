from django.conf import settings

from src.shared.communication import Consumer, Producer
from src.shared.communication.brokers import RedisPubSubBroker
from src.shared.communication.storages import RedisStorage
from shared.communication.dns import build_dns as _build_dns


_broker = RedisPubSubBroker(
    _build_dns(
        provider=settings.COMMUNICATION_BROKER_BACKEND,
        user=settings.COMMUNICATION_BROKER_USER,
        password=settings.COMMUNICATION_BROKER_PASSWORD,
        host=settings.COMMUNICATION_BROKER_HOST,
        port=settings.COMMUNICATION_BROKER_PORT,
        db=settings.COMMUNICATION_BROKER_NAME,
    )
)
_storage = RedisStorage(
    _build_dns(
        provider=settings.COMMUNICATION_STORAGE_BACKEND,
        user=settings.COMMUNICATION_STORAGE_USER,
        password=settings.COMMUNICATION_STORAGE_PASSWORD,
        host=settings.COMMUNICATION_STORAGE_HOST,
        port=settings.COMMUNICATION_STORAGE_PORT,
        db=settings.COMMUNICATION_STORAGE_NAME,
    )
)
producer = Producer(_broker, _storage)
consumer = Consumer(_broker, _storage)
