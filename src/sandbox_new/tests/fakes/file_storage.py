"""In-memory stand-in for the object store.

Subclasses the real port, so a change to it breaks this at import time instead of
letting the two drift apart. ``objects`` is the whole observable state: what a test
asserts on is what is stored, keyed the way the domain keys it.

``put`` reads the file object from wherever its cursor is, exactly as the boto3 upload
does, so a caller that hashes an upload and forgets to rewind it stores short bytes
here too instead of quietly passing.

The ``fail_*`` attributes make one operation raise. They exist for the reaper, whose
whole point is surviving a half-finished pass: ``fail_key`` narrows a failure to a
single key, so a pass can fail on one object and succeed on the rest.
"""

from typing import BinaryIO

from manager.application.ports import AbstractFileStorage

__all__ = ["FakeFileStorage"]


class FakeFileStorage(AbstractFileStorage):
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.fail_put: Exception | None = None
        self.fail_get: Exception | None = None
        self.fail_delete: Exception | None = None
        # None makes the configured failure apply to every key.
        self.fail_key: str | None = None

    async def put(self, key: str, file: BinaryIO):
        self._refuse(self.fail_put, key)
        self.objects[key] = file.read()

    async def get(self, key: str) -> bytes:
        # Before the lookup: an unreachable store does not know whether the key exists.
        self._refuse(self.fail_get, key)
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]

    async def delete(self, key: str):
        self._refuse(self.fail_delete, key)
        # No complaint about a key that is not there: the port promises as much, and
        # the reaper repeats a half-finished pass on that promise.
        self.objects.pop(key, None)

    def _refuse(self, error: Exception | None, key: str):
        """Raise the configured failure, when one is set and it covers this key."""
        if error is None:
            return
        if self.fail_key is not None and self.fail_key != key:
            return
        raise error
