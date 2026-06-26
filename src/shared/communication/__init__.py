"""
Transport messaging between microservices.

Provides Producer and Consumer that exchange messages over a pluggable broker,
optionally offloading large payloads to a separate storage backend.

Add a new transport or store by implementing AbstractBroker / AbstractStorage
and injecting it — Producer and Consumer stay unchanged.

To change default payload size threshold for all producers set DEFAULT_PAYLOAD_SIZE_THRESHOLD in the env.
"""

from .message import Message
from .producer import Producer
from .consumer import Consumer
from .errors import (
    CommunicationError,
    BrokerError,
    BrokerOperationError,
    StorageError,
    StorageOperationError,
)

__all__ = [
    "Message",
    "Producer",
    "Consumer",
    "CommunicationError",
    "BrokerError",
    "BrokerOperationError",
    "StorageError",
    "StorageOperationError",
]
