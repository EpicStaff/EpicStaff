from functools import wraps
from types import MappingProxyType
from typing import TYPE_CHECKING

from foundation.utils.lazy import LazyImport

if TYPE_CHECKING:
    from botocore import exceptions as boto3_exceptions
else:
    boto3_exceptions = LazyImport("botocore.exceptions")

__all__ = [
    "S3BucketAlreadyExistsError",
    "S3BucketError",
    "S3BucketNotExistError",
    "S3ConfigurationError",
    "S3FileStorageError",
    "S3ObjectError",
    "S3ObjectNotExistError",
    "S3UnavailableError",
]

class S3FileStorageError(Exception):
    """Base error for all S3 file storage failures."""

    def __init__(self, message: str, *, code: str | None = None, bucket: str | None = None, key: str | None = None):
        """Store the failure message plus whatever S3 context is known.

        Args:
            message: Human-readable description of the failure.
            code: S3 error code (e.g. `NoSuchBucket`), when raised from a `ClientError`.
            bucket: Bucket the failing call was scoped to, if known.
            key: Object key the failing call was scoped to, if known.
        """
        super().__init__(message)
        self.code = code
        self.bucket = bucket
        self.key = key


class S3BucketError(S3FileStorageError):
    """Base error for bucket-level failures."""


class S3BucketNotExistError(S3BucketError):
    """The bucket does not exist."""


class S3BucketAlreadyExistsError(S3BucketError):
    """The bucket already exists, owned by this account or another."""


class S3ObjectError(S3FileStorageError):
    """Base error for object-level failures."""


class S3ObjectNotExistError(S3ObjectError):
    """The object key does not exist in the bucket."""


class S3UnavailableError(S3FileStorageError):
    """The S3 endpoint could not be reached or timed out."""


class S3ConfigurationError(S3FileStorageError):
    """The client is misconfigured: bad credentials or invalid call parameters."""


ERRORS_MAP = MappingProxyType({
    # bucket errors
    "NoSuchBucket": S3BucketNotExistError,
    "BucketAlreadyExists": S3BucketAlreadyExistsError,
    "BucketAlreadyOwnedByYou": S3BucketAlreadyExistsError,

    # object errors
    "NoSuchKey": S3ObjectNotExistError,
})


def handle_error(fn):
    """Wrap a bound S3FileStorage/S3Bucket/S3Object method to raise domain exceptions.

    Translates a `ClientError` via `ERRORS_MAP` (falling back to `S3FileStorageError`),
    connection/timeout failures to `S3UnavailableError`, and bad credentials or parameters
    to `S3ConfigurationError`. The bucket/key on the raised exception come from
    `self._bucket`/`self._name`/`self._key` of the wrapped method's first argument, when set.

    Args:
        fn: Bound method of `S3FileStorage`, `S3Bucket` or `S3Object`.

    Returns:
        `fn`, wrapped so its boto3/botocore exceptions become domain exceptions.
    """
    @wraps(fn)
    def wrap(*args, **kwargs):
        self = args[0] if args else None
        bucket = getattr(self, "_bucket", None) or getattr(self, "_name", None)
        key = getattr(self, "_key", None)
        try:
            return fn(*args, **kwargs)
        except boto3_exceptions.ClientError as e:
            code = e.response["Error"]["Code"]
            message = e.response["Error"]["Message"]
            error_class = ERRORS_MAP.get(code, S3FileStorageError)
            raise error_class(message, code=code, bucket=bucket, key=key) from e
        except (
            boto3_exceptions.EndpointConnectionError,
            boto3_exceptions.ConnectTimeoutError,
            boto3_exceptions.ReadTimeoutError,
        ) as e:
            raise S3UnavailableError(str(e), bucket=bucket, key=key) from e
        except (
            boto3_exceptions.ParamValidationError,
            boto3_exceptions.NoCredentialsError,
        ) as e:
            raise S3ConfigurationError(str(e), bucket=bucket, key=key) from e
    return wrap
