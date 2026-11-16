"""The storage backend's admin API replaced by a recording fake, for tests that mint
temporary storage credentials through `session_credential_service`.

Exposed to `tests/services_tests/` and `tests/storage_tests/` by their conftest.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

GATEWAY_PATH = "storage_credentials.services.session_credential_service.StorageAdminGateway"
ORG_CREDENTIALS_PATH = "storage_credentials.services.session_credential_service.org_credential_store.get"


class FakeStorageGateway:
    """Records the service accounts minted and deleted in the storage backend."""

    def __init__(self, delete_error: Exception | None = None):
        self.created: list[dict] = []
        self.deleted: list[str] = []
        self.delete_error = delete_error

    def __call__(self, *args, **kwargs):
        return self

    async def create_service_account(self, **kwargs):
        self.created.append(kwargs)
        return f"temp-access-{len(self.created)}", f"temp-secret-{len(self.created)}"

    async def delete_service_account(self, access_key):
        if self.delete_error is not None:
            raise self.delete_error
        self.deleted.append(access_key)

    async def close(self):
        pass


@pytest.fixture
def gateway():
    fake = FakeStorageGateway()
    with (
        patch(GATEWAY_PATH, fake),
        patch(ORG_CREDENTIALS_PATH, return_value=SimpleNamespace(access_key="org-access", secret_key="org-secret")),
    ):
        yield fake
