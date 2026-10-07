"""The port for provisioning and revoking scoped storage credentials.

The adapter talks to the object store's admin API to mint a short-lived service
account confined to one org's prefixes, and to delete it afterwards. The S3 policy
shape and the admin protocol are the adapter's concern; the application only asks
for credentials scoped to an org and its allowed paths.
"""

import abc

from worker.domain.models import StorageCredentials

__all__ = ["AbstractStorageCredentials"]


class AbstractStorageCredentials(abc.ABC):
    @abc.abstractmethod
    async def provision(self, *, org_prefix: str, allowed_paths: list[str]) -> StorageCredentials:
        """Create credentials scoped to ``org_prefix`` and ``allowed_paths``."""

    @abc.abstractmethod
    async def revoke(self, access_key: str) -> None:
        """Delete the service account identified by ``access_key``."""
