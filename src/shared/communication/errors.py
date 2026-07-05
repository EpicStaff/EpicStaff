class CommunicationError(Exception):
    """Base error for the communication package."""


class StorageError(CommunicationError):
    """Base error for the storage."""


class StorageOperationError(StorageError):
    """A storage operation failed.

    Args:
        operation: Failed operation.
        key: Storage key involved.
    """

    def __init__(self, operation: str, key: str):
        self.operation = operation
        self.key = key
        super().__init__(f"Storage {operation!r} failed for key {key!r}.")


class BrokerError(CommunicationError):
    """Base error for the broker."""


class BrokerOperationError(BrokerError):
    """A broker operation failed.

    Args:
        operation: Failed operation.
        channel: Channel involved.
    """

    def __init__(self, operation: str, channel: str):
        self.operation = operation
        self.channel = channel
        super().__init__(f"Broker {operation!r} failed on channel {channel!r}.")
