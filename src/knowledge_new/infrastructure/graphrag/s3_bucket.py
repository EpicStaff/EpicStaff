from functools import cache
from urllib.parse import urlsplit

from foundation.s3_file_storage import S3Bucket, S3FileStorage


def parse_endpoint(endpoint: str) -> tuple[bool, str, int]:
    """Split a storage URL such as `https://storage:9000` into `(is_secure, host, port)`.

    Raises:
        ValueError: If `endpoint` is not an http or https URL with a host and a port.
    """
    parts = urlsplit(endpoint)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.port is None:
        raise ValueError(
            f"Storage endpoint must be an http(s) URL with a host and a port, got {endpoint!r}."
        )
    return parts.scheme == "https", parts.hostname, parts.port


@cache
def open_bucket(endpoint: str, bucket: str, access_key: str, secret_key: str) -> S3Bucket:
    """Return a handle to `bucket`; calls with the same arguments share one boto3 client.

    graphrag builds a new `S3Storage` for every storage it opens, so the client is
    cached here rather than created per storage.
    """
    use_ssl, host, port = parse_endpoint(endpoint)
    return S3FileStorage(
        host=host, port=port, user=access_key, password=secret_key, use_ssl=use_ssl
    ).bucket(bucket)
