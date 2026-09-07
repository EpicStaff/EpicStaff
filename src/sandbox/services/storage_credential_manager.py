import json
import posixpath
import tempfile
from typing import Any
from datetime import timedelta, datetime, timezone

from loguru import logger
from miniopy_async import MinioAdmin as MinioAdminClient
from miniopy_async.credentials import StaticProvider


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
        http, endpoint = value.split('://')
        return http == 'https', endpoint

    async def create(self, policy: dict[str, Any]) -> tuple[str, str]:
        """Create a user in minio and return generated credentials"""
        expiration = (datetime.now(timezone.utc) + self._expiration).strftime("%Y-%m-%dT%H:%M:%SZ")
        with tempfile.NamedTemporaryFile("w", suffix=".json") as policy_file:
            json.dump(policy, policy_file)
            policy_file.flush()
            raw = await self._client.add_service_account(
                policy_file=policy_file.name,
                expiration=expiration,
            )
        credentials = json.loads(raw)["credentials"]
        return credentials["accessKey"], credentials["secretKey"]

    async def revoke(self, temp_access_key: str):
        """Revoke credentials for a user in minio"""
        await self._client.delete_service_account(temp_access_key)

    def build_policy(self, allowed_bucket: str, allowed_folders: set[str]) -> dict[str, Any]:
        """Build policy for a minio user"""
        if not allowed_folders:
            raise CredentialManagerError("No folders provided.")

        bucket = f"arn:aws:s3:::{allowed_bucket}"
        prefixes = sorted(f"{self._normalize_path(f)}" for f in allowed_folders)
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
                    "Condition": {
                        "StringLike": {
                            "s3:prefix": prefixes
                        }
                    }
                },

                # Let the client's mandatory GET ?location= probe pass.
                {
                    "Effect": "Allow",
                    "Action": ["s3:GetBucketLocation"],
                    "Resource": [bucket]
                },
            ]
        }

    @staticmethod
    def _normalize_path(path: str) -> str:
        stripped = path.strip()
        normalized = posixpath.normpath(stripped) if stripped else ""
        if normalized in ("", "."):
            raise CredentialManagerError(
                "Empty path is not allowed (would grant bucket-wide access)."
            )
        if normalized.startswith(".."):
            raise CredentialManagerError(f"Path traversal in path: '{path}'")

        return f'{normalized}/*' if stripped.endswith('/') else normalized