"""
Transport messaging between microservices.

Provides Producer and Consumer that exchange messages over a pluggable broker,
optionally offloading large payloads to a separate storage backend.

Add a new transport or store by implementing AbstractBroker / AbstractStorage
and injecting it — Producer and Consumer stay unchanged.

To change default payload size threshold for all producers set DEFAULT_PAYLOAD_SIZE_THRESHOLD in the env.
"""

from .consumer import Consumer
from .errors import (
    BrokerError,
    BrokerOperationError,
    CommunicationError,
    StorageError,
    StorageOperationError,
)
from .message import Message
from .producer import Producer

__all__ = [
    "BrokerError",
    "BrokerOperationError",
    "CommunicationError",
    "Consumer",
    "Message",
    "Producer",
    "StorageError",
    "StorageOperationError",
]
