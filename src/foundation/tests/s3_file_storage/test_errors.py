import pytest
from botocore.exceptions import (
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
    ParamValidationError,
    ReadTimeoutError,
)

from foundation.s3_file_storage.errors import (
    S3BucketAlreadyExistsError,
    S3BucketNotExistError,
    S3ConfigurationError,
    S3FileStorageError,
    S3ObjectNotExistError,
    S3UnavailableError,
    handle_error,
)

from .conftest import client_error


class _Dummy:
    """Stand-in for the self argument handle_error inspects for bucket/key context."""

    def __init__(self, *, bucket=None, name=None, key=None):
        self._bucket = bucket
        self._name = name
        self._key = key


@pytest.mark.parametrize(
    "code, expected_cls",
    [
        ("NoSuchBucket", S3BucketNotExistError),
        ("BucketAlreadyExists", S3BucketAlreadyExistsError),
        ("BucketAlreadyOwnedByYou", S3BucketAlreadyExistsError),
        ("NoSuchKey", S3ObjectNotExistError),
        ("SomeUnknownCode", S3FileStorageError),
    ],
)
def test_client_error_maps_to_domain_exception(code, expected_cls):
    @handle_error
    def raise_it(self):
        raise client_error(code)

    with pytest.raises(expected_cls) as exc_info:
        raise_it(_Dummy(name="bkt", key="k"))
    assert exc_info.value.code == code
    assert exc_info.value.bucket == "bkt"
    assert exc_info.value.key == "k"


def test_bucket_context_prefers_bucket_over_name():
    @handle_error
    def raise_it(self):
        raise client_error("NoSuchKey")

    with pytest.raises(S3ObjectNotExistError) as exc_info:
        raise_it(_Dummy(bucket="from-bucket", name="from-name"))
    assert exc_info.value.bucket == "from-bucket"


def test_context_is_none_when_self_has_no_bucket_or_key():
    @handle_error
    def raise_it(self):
        raise client_error("NoSuchBucket")

    with pytest.raises(S3BucketNotExistError) as exc_info:
        raise_it(_Dummy())
    assert exc_info.value.bucket is None
    assert exc_info.value.key is None


@pytest.mark.parametrize(
    "error",
    [
        EndpointConnectionError(endpoint_url="http://x"),
        ConnectTimeoutError(endpoint_url="http://x"),
        ReadTimeoutError(endpoint_url="http://x"),
    ],
)
def test_connection_errors_map_to_unavailable(error):
    @handle_error
    def raise_it(self):
        raise error

    with pytest.raises(S3UnavailableError):
        raise_it(_Dummy())


@pytest.mark.parametrize(
    "error",
    [
        ParamValidationError(report="bad params"),
        NoCredentialsError(),
    ],
)
def test_bad_credentials_or_params_map_to_configuration_error(error):
    @handle_error
    def raise_it(self):
        raise error

    with pytest.raises(S3ConfigurationError):
        raise_it(_Dummy())


def test_unrelated_exceptions_propagate_unchanged():
    @handle_error
    def raise_it(self):
        raise RuntimeError("not an s3 error")

    with pytest.raises(RuntimeError):
        raise_it(_Dummy())


def test_successful_call_passes_through():
    @handle_error
    def succeed(self):
        return "ok"

    assert succeed(_Dummy()) == "ok"
