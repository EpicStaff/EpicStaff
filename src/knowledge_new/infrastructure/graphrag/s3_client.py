from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from miniopy_async import Minio


def parse_endpoint(endpoint: str) -> tuple[bool, str]:
    """Split a storage URL such as `https://storage:9000` into `(is_secure, "storage:9000")`.

    Raises:
        ValueError: If `endpoint` is not an http or https URL with a host.
    """
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ValueError(f"Storage endpoint must be an http(s) URL with a host, got {endpoint!r}.")
    return parts.scheme == "https", parts.netloc


@asynccontextmanager
async def open_s3_client(
    *, endpoint: str, bucket: str, access_key: str, secret_key: str
) -> AsyncIterator[Minio]:
    """Yield a client owned by one operation and close its session afterwards.

    A client per operation keeps the session's lifetime equal to the operation's,
    so closing in `finally` never pulls the session out from under another call
    and a failed operation cannot leak it. The bucket is created on first use.
    """
    secure, host_and_port = parse_endpoint(endpoint)
    client = Minio(
        endpoint=host_and_port,
        secure=secure,
        access_key=access_key,
        secret_key=secret_key,
    )
    try:
        if not await client.bucket_exists(bucket):
            await client.make_bucket(bucket)
        yield client
    finally:
        await client.close_session()
