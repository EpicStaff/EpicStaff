import asyncio
from typing import TYPE_CHECKING, BinaryIO

from foundation.utils.lazy import LazyImport

if TYPE_CHECKING:
    from boto3.session import Session as Boto3Session
    from botocore import exceptions as boto3_exceptions
    from botocore.config import Config as Boto3Config
else:
    Boto3Session = LazyImport("boto3.session", "Session")
    Boto3Config = LazyImport("botocore.config", "Config")
    boto3_exceptions = LazyImport("botocore.exceptions")

from .errors import handle_error

__all__ = ["S3Bucket", "S3FileStorage", "S3Object"]


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
            One handle per matching object, not necessarily sorted.
        """
        kwargs = {"Bucket": self._name}
        if prefix is not None:
            kwargs["Prefix"] = prefix
        pagination_config = {"MaxItems": max} if max is not None else {}
        paginator = self._client.get_paginator("list_objects_v2")
        objects: list[S3Object] = []
        for page in paginator.paginate(**kwargs, PaginationConfig=pagination_config):
            objects.extend(
                S3Object(self._client, self._name, d["Key"]) for d in page.get("Contents", [])
            )
        return objects

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


class S3Object:
    """Handle to one object (key) in a bucket. Construct via `S3Bucket.object()`, not directly."""

    def __init__(self, client, bucket: str, key: str):
        self._client = client
        self._bucket = bucket
        self._key = key

    @property
    def bucket(self) -> str:
        return self._bucket

    @property
    def key(self) -> str:
        return self._key

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
    def read(self) -> bytes:
        """Return the full object body.

        Note:
            Reads the whole object into memory; there is no streaming variant yet.

        Raises:
            S3ObjectNotExistError: No object with this key exists in the bucket.
        """
        response = self._client.get_object(Bucket=self._bucket, Key=self._key)
        return response["Body"].read()

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

    async def aread(self) -> bytes:
        """Async version of `read`, run in a worker thread."""
        return await asyncio.to_thread(self.read)

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
