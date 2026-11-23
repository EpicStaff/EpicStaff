from datetime import UTC, datetime

from foundation.s3_file_storage import S3ObjectError, S3ObjectNotExistError


class InMemoryS3Bucket:
    """The async part of foundation's `S3Bucket` the service uses, holding objects in a dict."""

    def __init__(self):
        self.objects_by_key: dict[str, bytes] = {}
        self.refused_keys: set[str] = set()

    def object(self, key: str) -> "InMemoryS3Object":
        return InMemoryS3Object(self, key)

    def objects(self, prefix: str | None = None) -> list["InMemoryS3Object"]:
        return [
            InMemoryS3Object(self, key, size=len(data))
            for key, data in sorted(self.objects_by_key.items())
            if prefix is None or key.startswith(prefix)
        ]

    async def aobjects(self, prefix: str | None = None) -> list["InMemoryS3Object"]:
        return self.objects(prefix)

    async def adelete_objects(self, keys) -> None:
        keys = list(keys)
        refused = [key for key in keys if key in self.refused_keys]
        if refused:
            raise S3ObjectError("AccessDenied", code="AccessDenied", key=refused[0])
        for key in keys:
            self.objects_by_key.pop(key, None)


class InMemoryS3Object:
    def __init__(self, bucket: InMemoryS3Bucket, key: str, size: int | None = None):
        self._bucket = bucket
        self.key = key
        self.size = size

    def _data(self) -> bytes:
        try:
            return self._bucket.objects_by_key[self.key]
        except KeyError as error:
            raise S3ObjectNotExistError("missing", code="NoSuchKey", key=self.key) from error

    async def aread(self) -> bytes:
        return self._data()

    async def awrite(self, data: bytes) -> None:
        self._bucket.objects_by_key[self.key] = bytes(data)

    async def aupload(self, source) -> None:
        self._bucket.objects_by_key[self.key] = source.read()

    async def aexist(self) -> bool:
        return self.key in self._bucket.objects_by_key

    async def adelete(self) -> None:
        self._bucket.objects_by_key.pop(self.key, None)

    async def alast_modified(self) -> datetime:
        self._data()
        return datetime(2024, 1, 1, tzinfo=UTC)

    async def aiter_chunks(self, chunk_size: int):
        data = self._data()
        for start in range(0, len(data), chunk_size):
            yield data[start : start + chunk_size]
