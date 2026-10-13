"""Stand-in for the scoped storage credential port.

Hands out fixed keys so assertions can name them, and records what it was asked to
provision and revoke -- the orchestrator must always revoke what it provisioned.
"""

from worker.application.ports import AbstractStorageCredentials
from worker.domain.models import StorageCredentials

__all__ = ["FAKE_ACCESS_KEY", "FAKE_SECRET_KEY", "FakeStorageCredentials"]

FAKE_ACCESS_KEY = "FAKEACCESSKEY1234567"
FAKE_SECRET_KEY = "fakesecretkey0123456789abcdefghijklmnop"


class FakeStorageCredentials(AbstractStorageCredentials):
    def __init__(self) -> None:
        self.provisioned: list[tuple[str, list[str]]] = []
        self.revoked: list[str] = []
        self.fail_provision: Exception | None = None
        self.fail_revoke: Exception | None = None

    async def provision(self, *, org_prefix: str, allowed_paths: list[str]) -> StorageCredentials:
        if self.fail_provision is not None:
            raise self.fail_provision
        self.provisioned.append((org_prefix, list(allowed_paths)))
        return StorageCredentials(access_key=FAKE_ACCESS_KEY, secret_key=FAKE_SECRET_KEY)

    async def revoke(self, access_key: str) -> None:
        if self.fail_revoke is not None:
            raise self.fail_revoke
        self.revoked.append(access_key)
