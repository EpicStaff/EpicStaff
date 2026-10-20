from typing import BinaryIO

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

_MISSING_BUCKET_CODES = frozenset({"404", "NoSuchBucket"})
_MISSING_OBJECT_CODES = frozenset({"404", "NoSuchKey"})
_ALREADY_CREATED_CODES = frozenset({"BucketAlreadyOwnedByYou", "BucketAlreadyExists"})


class PackageFileMissingError(Exception):
    """The bucket holds no object under the package's storage key."""


def package_storage_key(identifier: str, version: str, sha256: str) -> str:
    return f"packages/{identifier}/{version}/{sha256}.esplugin"


class PluginPackageStore:
    """Plugin package files, in a bucket of their own that is created on first use.

    Kept apart from organizations' storage: packages belong to the deployment, not to an
    organization, and no organization quota or credential reaches them.
    """

    def __init__(self, client, bucket: str):
        self._client = client
        self._bucket = bucket
        self._bucket_ready = False

    def save(self, key: str, file: BinaryIO) -> None:
        """Upload `file` from its current position to `key`, replacing any object there."""
        self._ensure_bucket()
        self._client.upload_fileobj(file, self._bucket, key)

    def download(self, key: str, destination: BinaryIO) -> None:
        """Write the object at `key` into `destination`.

        Raises:
            PackageFileMissingError: There is no object at `key`.
        """
        try:
            self._client.download_fileobj(self._bucket, key, destination)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in _MISSING_OBJECT_CODES:
                raise PackageFileMissingError(key) from error
            raise

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket, Key=key)

    def _ensure_bucket(self) -> None:
        if self._bucket_ready:
            return
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in _MISSING_BUCKET_CODES:
                raise
            self._create_bucket()
        self._bucket_ready = True

    def _create_bucket(self) -> None:
        try:
            self._client.create_bucket(Bucket=self._bucket)
        except ClientError as error:
            # Another worker created it between the check and the create.
            if error.response.get("Error", {}).get("Code") not in _ALREADY_CREATED_CODES:
                raise


def get_package_store() -> PluginPackageStore:
    """Return the store configured by the storage settings and PLUGINS_STORAGE_BUCKET."""
    client = boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_ENDPOINT or None,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY,
        aws_secret_access_key=settings.STORAGE_SECRET_KEY,
        config=Config(connect_timeout=10, read_timeout=300),
    )
    return PluginPackageStore(client, settings.PLUGINS_STORAGE_BUCKET)
