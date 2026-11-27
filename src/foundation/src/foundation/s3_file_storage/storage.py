import asyncio
from collections.abc import AsyncIterator, Iterable, Iterator
from datetime import datetime
from typing import TYPE_CHECKING, BinaryIO

from foundation.utils import humanize
from foundation.utils.lazy import LazyImport

if TYPE_CHECKING:
    from boto3.session import Session as Boto3Session
    from botocore import exceptions as boto3_exceptions
    from botocore.config import Config as Boto3Config
else:
    Boto3Session = LazyImport("boto3.session", "Session")
    Boto3Config = LazyImport("botocore.config", "Config")
    boto3_exceptions = LazyImport("botocore.exceptions")

from .errors import S3ObjectError, S3ObjectNotExistError, handle_error

__all__ = ["S3Bucket", "S3FileStorage", "S3Object"]

# The most keys one `DeleteObjects` request may name.
_DELETE_OBJECTS_BATCH_SIZE = 1000
# Bytes of an object held in memory at a time while it is streamed.
_DEFAULT_CHUNK_SIZE = humanize.to_byte_size("1mb")


class S3FileStorage:
    """Entry point to an S3-compatible object store.

    Holds one boto3 client, shared by every `S3Bucket`/`S3Object` created through it.
    """

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        use_ssl: bool = False,
        region_name: str = "us-east-1",
        connect_timeout: int = 10,
        read_timeout: int = 60,
        retries: int = 3,
        max_pool_contections: int = 20,
    ):
        """Build the boto3 client this storage and every bucket/object under it shares.

        Args:
            host: S3 host, without scheme.
            port: S3 port.
            user: Access key id.
            password: Secret access key.
            use_ssl: Connect over `https` instead of `http`.
            region_name: Signing region, pinned explicitly so it does not depend on ambient
                `AWS_DEFAULT_REGION`/`~/.aws/config` in the container.
            connect_timeout: Seconds to wait for a TCP connection.
            read_timeout: Seconds to wait for a response once connected.
            retries: Max attempts per request.
            max_pool_contections: Size of the client's HTTP connection pool.
        """
        self._session = Boto3Session()
        self._client = self._session.client(
            service_name="s3",
            endpoint_url=f"http{'s' if use_ssl else ''}://{host}:{port}",
            aws_access_key_id=user,
            aws_secret_access_key=password,
            region_name=region_name,
            config=Boto3Config(
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                retries={"mode": "standard", "max_attempts": retries},
                max_pool_connections=max_pool_contections,
            ),
        )

    def bucket(self, bucket: str) -> "S3Bucket":
        """Return a handle to `bucket`. Does not check that it exists."""
        return S3Bucket(self._client, bucket)

    @handle_error
    def buckets(self, max: int | None = None) -> list["S3Bucket"]:
        """List every bucket, paging through `ListBuckets` until exhausted or `max` is reached.

        Note:
            No `prefix` filter: RustFS 1.0.0 ignores `ListBuckets`' `Prefix`/`MaxBuckets`
            request parameters and always returns every bucket, so a server-side filter here
            would silently do nothing. `max` still works -- it is applied client-side.

        Args:
            max: Stop once this many buckets have been collected.

        Returns:
            One handle per bucket, not necessarily sorted.
        """
        kwargs: dict = {}
        buckets: list[S3Bucket] = []
        while True:
            response = self._client.list_buckets(**kwargs)
            buckets.extend(S3Bucket(self._client, d["Name"]) for d in response.get("Buckets", []))
            if max is not None and len(buckets) >= max:
                return buckets[:max]
            continuation_token = response.get("ContinuationToken")
            if not continuation_token:
                return buckets
            kwargs["ContinuationToken"] = continuation_token

    async def abuckets(self, max: int | None = None) -> list["S3Bucket"]:
        """Async version of `buckets`, run in a worker thread."""
        return await asyncio.to_thread(self.buckets, max)


class S3Bucket:
    """Handle to one bucket. Construct via `S3FileStorage.bucket()`, not directly."""

    def __init__(self, client, name: str):
        self._client = client
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @handle_error
    def exist(self) -> bool:
        """Return whether this bucket exists.

        Note:
            A missing/unreachable bucket and this one being genuinely absent both answer
            `False` here; `HeadBucket`'s 404 doesn't distinguish the two.
        """
        try:
            self._client.head_bucket(Bucket=self._name)
        except boto3_exceptions.ClientError as e:
            if e.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                return False
            raise
        return True

    @handle_error
    def create(self):
        """Create this bucket.

        Raises:
            S3BucketAlreadyExistsError: A bucket with this name already exists.
        """
        self._client.create_bucket(Bucket=self._name)

    @handle_error
    def delete(self):
        """Delete this bucket. The bucket must be empty.

        Raises:
            S3BucketNotExistError: No bucket with this name exists.
        """
        self._client.delete_bucket(Bucket=self._name)

    def object(self, key: str) -> "S3Object":
        """Return a handle to the object at `key` in this bucket. Does not check that it exists."""
        return S3Object(self._client, self._name, key)

    @handle_error
    def objects(self, prefix: str | None = None, max: int | None = None) -> list["S3Object"]:
        """List objects in this bucket, paging through `ListObjectsV2` until exhausted.

        Args:
            prefix: Only return objects whose key starts with this.
            max: Stop once this many objects have been collected.

        Returns:
            One handle per matching object, not necessarily sorted, each with the
            `size` the listing reported.
        """
        kwargs = {"Bucket": self._name}
        if prefix is not None:
            kwargs["Prefix"] = prefix
        pagination_config = {"MaxItems": max} if max is not None else {}
        paginator = self._client.get_paginator("list_objects_v2")
        objects: list[S3Object] = []
        for page in paginator.paginate(**kwargs, PaginationConfig=pagination_config):
            objects.extend(
                S3Object(self._client, self._name, d["Key"], size=d["Size"])
                for d in page.get("Contents", [])
            )
        return objects

    @handle_error
    def delete_objects(self, keys: Iterable[str]):
        """Delete every object in `keys`, up to 1000 per `DeleteObjects` request.

        A key that doesn't exist is skipped, as in `S3Object.delete`.

        Raises:
            S3ObjectError: The store refused to delete some keys of a batch. The error
                carries the first refusal's code and key; earlier batches stay deleted.
        """
        keys = list(keys)
        for start in range(0, len(keys), _DELETE_OBJECTS_BATCH_SIZE):
            batch = keys[start : start + _DELETE_OBJECTS_BATCH_SIZE]
            response = self._client.delete_objects(
                Bucket=self._name,
                Delete={"Objects": [{"Key": key} for key in batch], "Quiet": True},
            )
            if failures := response.get("Errors"):
                first = failures[0]
                raise S3ObjectError(
                    f"{len(failures)} object(s) were not deleted: {first.get('Message')}",
                    code=first.get("Code"),
                    bucket=self._name,
                    key=first.get("Key"),
                )

    async def aexist(self) -> bool:
        """Async version of `exist`, run in a worker thread."""
        return await asyncio.to_thread(self.exist)

    async def acreate(self):
        """Async version of `create`, run in a worker thread."""
        await asyncio.to_thread(self.create)

    async def adelete(self):
        """Async version of `delete`, run in a worker thread."""
        await asyncio.to_thread(self.delete)

    async def aobjects(self, prefix: str | None = None, max: int | None = None) -> list["S3Object"]:
        """Async version of `objects`, run in a worker thread."""
        return await asyncio.to_thread(self.objects, prefix, max)

    async def adelete_objects(self, keys: Iterable[str]):
        """Async version of `delete_objects`, run in a worker thread."""
        await asyncio.to_thread(self.delete_objects, keys)


class S3Object:
    """Handle to one object (key) in a bucket. Construct via `S3Bucket.object()`, not directly."""

    def __init__(self, client, bucket: str, key: str, size: int | None = None):
        self._client = client
        self._bucket = bucket
        self._key = key
        self._size = size

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def key(self) -> str:
        return self._key

    @property
    def size(self) -> int | None:
        """Size in bytes as `S3Bucket.objects()` listed it; None on a handle from `S3Bucket.object()`."""
        return self._size

    @handle_error
    def exist(self) -> bool:
        """Return whether this object exists.

        Note:
            A missing bucket also answers `False` here, same as a missing key;
            `HeadObject`'s 404 doesn't distinguish the two.
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=self._key)
        except boto3_exceptions.ClientError as e:
            if e.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                return False
            raise
        return True

    @handle_error
    def last_modified(self) -> datetime:
        """Return when this object was last written, as a timezone-aware datetime.

        Raises:
            S3ObjectNotExistError: No object with this key exists in the bucket.
        """
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=self._key)
        except boto3_exceptions.ClientError as e:
            # HeadObject answers without a body, so a missing key is a bare 404, not NoSuchKey.
            if e.response["ResponseMetadata"]["HTTPStatusCode"] == 404:
                raise S3ObjectNotExistError(
                    "The specified key does not exist.",
                    code="NoSuchKey",
                    bucket=self._bucket,
                    key=self._key,
                ) from e
            raise
        return response["LastModified"]

    @handle_error
    def read(self) -> bytes:
        """Return the full object body.

        Note:
            Reads the whole object into memory; there is no streaming variant yet.

        Raises:
            S3ObjectNotExistError: No object with this key exists in the bucket.
        """
        response = self._client.get_object(Bucket=self._bucket, Key=self._key)
        return response["Body"].read()

    def iter_chunks(self, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> Iterator[bytes]:
        """Yield the object's body in chunks of up to `chunk_size` bytes.

        Only one chunk is in memory at a time, unlike `read`. The connection is released
        when the iteration ends, also when it is abandoned early.

        Raises:
            S3ObjectNotExistError: No object with this key exists in the bucket; raised
                on the first iteration.
        """
        body = self._open_body()
        try:
            while chunk := self._read_chunk(body, chunk_size):
                yield chunk
        finally:
            body.close()

    @handle_error
    def _open_body(self):
        return self._client.get_object(Bucket=self._bucket, Key=self._key)["Body"]

    @handle_error
    def _read_chunk(self, body, chunk_size: int) -> bytes:
        return body.read(chunk_size)

    @handle_error
    def write(self, data: bytes):
        """Upload `data` as this object's body in one `PutObject` call, overwriting it if it exists."""
        self._client.put_object(Bucket=self._bucket, Key=self._key, Body=data)

    @handle_error
    def upload(self, file: BinaryIO):
        """Send `file`'s contents to this object in parts, overwriting it if it exists.

        The body never has to be in memory in one piece, unlike `write`: boto3 reads
        `file` in chunks and switches to a multipart upload once it is large enough.

        Args:
            file: Readable binary file object, consumed from its current position.
        """
        self._client.upload_fileobj(file, self._bucket, self._key)

    @handle_error
    def download(self, file: BinaryIO):
        """Fetch this object's body in parts and write it into `file`.

        Takes a sink rather than returning the body, because a multipart download
        fetches ranges in parallel and writes them out of order: there is no ordered
        stream to hand back without first assembling the whole body in memory, which
        is what this exists to avoid. A sink without `seek` makes boto3 fall back to
        a sequential download.

        Args:
            file: Writable binary file object, written from its current position.

        Raises:
            S3ObjectNotExistError: No object with this key exists in the bucket.
        """
        self._client.download_fileobj(self._bucket, self._key, file)

    @handle_error
    def delete(self):
        """Delete this object. A no-op if the key doesn't already exist."""
        self._client.delete_object(Bucket=self._bucket, Key=self._key)

    async def aexist(self) -> bool:
        """Async version of `exist`, run in a worker thread."""
        return await asyncio.to_thread(self.exist)

    async def alast_modified(self) -> datetime:
        """Async version of `last_modified`, run in a worker thread."""
        return await asyncio.to_thread(self.last_modified)

    async def aread(self) -> bytes:
        """Async version of `read`, run in a worker thread."""
        return await asyncio.to_thread(self.read)

    async def aiter_chunks(self, chunk_size: int = _DEFAULT_CHUNK_SIZE) -> AsyncIterator[bytes]:
        """Async version of `iter_chunks`; each chunk is read in a worker thread."""
        body = await asyncio.to_thread(self._open_body)
        try:
            while chunk := await asyncio.to_thread(self._read_chunk, body, chunk_size):
                yield chunk
        finally:
            body.close()

    async def awrite(self, data: bytes):
        """Async version of `write`, run in a worker thread."""
        await asyncio.to_thread(self.write, data)

    async def aupload(self, file: BinaryIO):
        await asyncio.to_thread(self.upload, file)

    async def adownload(self, file: BinaryIO):
        await asyncio.to_thread(self.download, file)

    async def adelete(self):
        """Async version of `delete`, run in a worker thread."""
        await asyncio.to_thread(self.delete)
