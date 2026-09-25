import json
import posixpath
import secrets
import string
import tempfile
from datetime import UTC, datetime, timedelta
from typing import Any

from miniopy_async import MinioAdmin as MinioAdminClient
from miniopy_async.credentials import StaticProvider
from miniopy_async.error import MinioAdminException
from utils.logger import logger

_ACCESS_KEY_ALPHABET = string.ascii_uppercase + string.digits
_SECRET_KEY_ALPHABET = string.ascii_letters + string.digits


class CredentialManagerError(Exception):
    pass


class StorageCredentialManager:
    def __init__(
        self,
        host: str,
        access_key: str,
        secret_key: str,
        expiration: timedelta = timedelta(hours=6),
    ):
        secure, endpoint = self._split_host(host)
        self._client = MinioAdminClient(
            endpoint=endpoint,
            credentials=StaticProvider(access_key, secret_key),
            secure=secure,
        )
        self._expiration = expiration

    @staticmethod
    def _split_host(value: str) -> tuple[bool, str]:
        http, endpoint = value.split("://")
        return http == "https", endpoint

    async def create(self, policy: dict[str, Any]) -> tuple[str, str]:
        """Create a scoped service account and return its credentials"""
        access_key, secret_key = self._generate_key_pair()
        expiration = (datetime.now(UTC) + self._expiration).strftime("%Y-%m-%dT%H:%M:%SZ")
        with tempfile.NamedTemporaryFile("w", suffix=".json") as policy_file:
            json.dump(policy, policy_file)
            policy_file.flush()
            try:
                await self._client.add_service_account(
                    access_key=access_key,
                    secret_key=secret_key,
                    policy_file=policy_file.name,
                    expiration=expiration,
                )
            except MinioAdminException:
                raise  # non-2xx: the server did not create the account
            except ValueError as error:
                # RustFS encrypts the 2xx response with an AEAD the client can't read.
                if str(error) != "Unknown AEAD ID 2":
                    await self._revoke_after_failed_create(access_key)
                    raise
            except BaseException:
                await self._revoke_after_failed_create(access_key)
                raise
        return access_key, secret_key

    @staticmethod
    def _generate_key_pair() -> tuple[str, str]:
        access_key = "".join(secrets.choice(_ACCESS_KEY_ALPHABET) for _ in range(20))
        secret_key = "".join(secrets.choice(_SECRET_KEY_ALPHABET) for _ in range(40))
        return access_key, secret_key

    async def _revoke_after_failed_create(self, access_key: str):
        # The request may have reached the server, so don't leave a live credential.
        try:
            await self.revoke(access_key)
        except Exception as error:
            logger.warning(
                "Cleanup of service account {} after failed create: {}", access_key, error
            )

    async def revoke(self, temp_access_key: str):
        """Revoke a scoped service account"""
        await self._client.delete_service_account(temp_access_key)

    def build_policy(
        self,
        allowed_bucket: str,
        org_prefix: str,
        allowed_paths: list[str] | None,
    ) -> dict[str, Any]:
        """Build policy for a minio user"""
        prefix = self._validate_org_prefix(org_prefix)
        folders = allowed_paths or ["/"]  # no explicit paths -> whole-org grant

        bucket = f"arn:aws:s3:::{allowed_bucket}"

        prefixes = sorted(
            self._assert_within_org(
                self._normalize_path(f"{prefix}/{path.strip().lstrip('/')}"), prefix
            )
            for path in folders
        )

        resources = [f"{bucket}/{prefix}" for prefix in prefixes]
        return {
            "Version": "2012-10-17",
            "Statement": [
                # Read/write/delete the actual files inside the allowed folders.
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                    "Resource": resources,
                },
                # List folder contents restricted to the allowed prefixes only.
                {
                    "Effect": "Allow",
                    "Action": ["s3:ListBucket"],
                    "Resource": [bucket],
                    "Condition": {"StringLike": {"s3:prefix": prefixes}},
                },
                # Let the client's mandatory GET ?location= probe pass.
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetBucketLocation"],
                    "Resource": [bucket],
                },
            ],
        }

    @staticmethod
    def _validate_org_prefix(org_prefix: str) -> str:
        prefix = org_prefix.strip("/")
        if (
            not prefix
            or "/" in prefix
            or prefix in (".", "..")
            or posixpath.normpath(prefix) != prefix
        ):
            raise CredentialManagerError(f"Invalid organization prefix: '{org_prefix}'")
        return prefix

    @staticmethod
    def _normalize_path(path: str) -> str:
        stripped = path.strip().replace("\\", "/")
        normalized = posixpath.normpath(stripped) if stripped else ""
        if normalized in ("", ".", "..", "/"):
            raise CredentialManagerError(
                "Empty path is not allowed (would grant bucket-wide access)."
            )
        return f"{normalized}/*" if stripped.endswith("/") else normalized

    @staticmethod
    def _assert_within_org(normalized: str, org_prefix: str) -> str:
        bare = normalized.removesuffix("/*")
        if bare != org_prefix and not bare.startswith(f"{org_prefix}/"):
            raise CredentialManagerError(
                f"Path escapes organization scope '{org_prefix}': '{normalized}'"
            )
        return normalized
