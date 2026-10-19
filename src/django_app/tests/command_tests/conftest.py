import pytest

from storage_credentials.services.org_provisioning_service import OrgStorageProvisioningService


@pytest.fixture(autouse=True)
def storage_server_accepts_new_users(monkeypatch):
    """Creating an organization creates its IAM user on the MinIO/RustFS server,
    which only exists inside the compose network; the credentials are still stored."""

    async def _create_storage_user(self, org_id, access_key, secret_key):
        return None

    monkeypatch.setattr(OrgStorageProvisioningService, "_provision_in_storage", _create_storage_user)
