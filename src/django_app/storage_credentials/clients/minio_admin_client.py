"""Thin async gateway over `miniopy_async.MinioAdmin`.

Ported from `sandbox/services/storage_credential_manager.py` (that file is
deleted as part of this change -- see `.claude/storage-credentials-plan.md`
section 6). The MinIO Admin API calls themselves were already correct and
verified there; this class only adds the org-level user operations
(`add_user`/`remove_user`/named-policy attach) that `sandbox` never needed.

Policy attachment for a named (non-service-account) MinIO user is a two-step
operation on this server version/client: `policy_add` registers the policy
under a name, then `policy_set` attaches that name to the user. There is no
single-call "inline" policy attach for a regular IAM user in `miniopy_async`
(unlike `add_service_account`, which does accept an inline `policy_file`).
"""

import json
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any

from miniopy_async import MinioAdmin as _MinioAdminClient
from miniopy_async.credentials import StaticProvider

from storage_credentials.exceptions import (
    TemporaryCredentialIssueError,
    TemporaryCredentialRevokeError,
)


class MinioAdminGateway:
    def __init__(self, host: str, access_key: str, secret_key: str):
        secure, endpoint = self._split_host(host)
        self._client = _MinioAdminClient(
            endpoint=endpoint,
            credentials=StaticProvider(access_key, secret_key),
            secure=secure,
        )

    @staticmethod
    def _split_host(value: str) -> tuple[bool, str]:
        http, endpoint = value.split("://")
        return http == "https", endpoint

    # --- org-level (long-lived) IAM user ---------------------------------

    async def add_user(self, access_key: str, secret_key: str) -> None:
        await self._client.user_add(access_key, secret_key)

    async def remove_user(self, access_key: str) -> None:
        """Removing the parent user cascades: MinIO revokes all of that
        user's service accounts along with it."""
        await self._client.user_remove(access_key)

    async def create_named_policy(
        self, policy_name: str, policy: dict[str, Any]
    ) -> None:
        with tempfile.NamedTemporaryFile("w", suffix=".json") as policy_file:
            json.dump(policy, policy_file)
            policy_file.flush()
            await self._client.policy_add(policy_name, policy_file.name)

    async def attach_named_policy(self, policy_name: str, user: str) -> None:
        await self._client.policy_set(policy_name, user=user)

    # --- per-execution (temporary) service account ------------------------

    async def create_service_account(
        self, policy: dict[str, Any], expiration: timedelta
    ) -> tuple[str, str]:
        """Mint a temporary service account scoped to `policy`. Returns
        (access_key, secret_key)."""
        expiration_str = (datetime.now(timezone.utc) + expiration).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".json") as policy_file:
                json.dump(policy, policy_file)
                policy_file.flush()
                raw = await self._client.add_service_account(
                    policy_file=policy_file.name,
                    expiration=expiration_str,
                )
            credentials = json.loads(raw)["credentials"]
            return credentials["accessKey"], credentials["secretKey"]
        except Exception as error:
            raise TemporaryCredentialIssueError(
                f"Failed to mint temporary service account: {error}",
                transient=True,
            ) from error

    async def delete_service_account(self, access_key: str) -> None:
        try:
            await self._client.delete_service_account(access_key)
        except Exception as error:
            raise TemporaryCredentialRevokeError(
                f"Failed to revoke service account '{access_key}': {error}"
            ) from error

    async def list_service_accounts(self, user: str) -> list[dict[str, Any]]:
        """Active service accounts of `user`, each carrying at least
        `accessKey` and `expiration` (ISO-8601, server-supplied)."""
        raw = await self._client.list_service_account(user)
        return json.loads(raw).get("accounts", [])
