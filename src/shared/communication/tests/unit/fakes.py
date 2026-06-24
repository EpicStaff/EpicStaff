from typing import Any, AsyncIterable, Iterable

from communication.brokers.abstract import AbstractBroker
from communication.storages.abstract import AbstractStorage


class FakeBroker(AbstractBroker):
    """In-memory broker that records sent messages and replays seeded frames.

    Args:
        frames: Optional list of dicts to replay from receive/areceive.
            Each dict is copied before yielding so tests can mutate freely.
    """

    def __init__(self, frames: list[dict[str, Any]] | None = None):
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self.async_sent: list[tuple[str, dict[str, Any]]] = []
        self._frames: list[dict[str, Any]] = frames if frames is not None else []

    def send(self, channel: str, data: dict[str, Any]):
        self.sent.append((channel, data))

    async def asend(self, channel: str, data: dict[str, Any]):
        self.async_sent.append((channel, data))

    def receive(self, channel: str) -> Iterable[dict[str, Any]]:
        for frame in self._frames:
            yield dict(frame)

    async def areceive(self, channel: str) -> AsyncIterable[dict[str, Any]]:
        for frame in self._frames:
            yield dict(frame)


class FakeStorage(AbstractStorage):
    """In-memory storage that records every operation.

    Args:
        store: Optional pre-populated dict mapping key -> bytes.
    """

    def __init__(self, store: dict[str, bytes] | None = None):
        self._store: dict[str, bytes] = store if store is not None else {}
        self.puts: list[tuple[str, bytes]] = []
        self.async_puts: list[tuple[str, bytes]] = []
        self.gets: list[str] = []
        self.async_gets: list[str] = []
        self.removes: list[str] = []
        self.async_removes: list[str] = []

    def put(self, key: str, payload: bytes):
        self._store[key] = payload
        self.puts.append((key, payload))

    async def aput(self, key: str, payload: bytes):
        self._store[key] = payload
        self.async_puts.append((key, payload))

    def get(self, key: str) -> bytes | None:
        self.gets.append(key)
        return self._store.get(key)

    async def aget(self, key: str) -> bytes | None:
        self.async_gets.append(key)
        return self._store.get(key)

    def remove(self, key: str):
        self.removes.append(key)
        self._store.pop(key, None)

    async def aremove(self, key: str):
        self.async_removes.append(key)
        self._store.pop(key, None)
