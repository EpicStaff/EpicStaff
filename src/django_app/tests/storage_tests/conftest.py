import tarfile
import zipfile
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from tables.models import Organization, OrganizationUser
from tables.models.rbac_models import Role
from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.local_backend import LocalStorageBackend
from tables.services.storage_service.manager import StorageManager


@pytest.fixture
def tmp_path(tmp_path_factory):
    """Override parent conftest's static tmp_path with pytest's real temp dir."""
    return tmp_path_factory.mktemp("storage")


@pytest.fixture
def local_backend(tmp_path):
    """LocalStorageBackend rooted at a real temp dir, no org prefix."""
    return LocalStorageBackend(root=str(tmp_path), organization_prefix="")


@pytest.fixture
def org(db):
    return Organization.objects.create(name="test-org")


@pytest.fixture
def org_user(db, org):
    role = Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)
    user = get_user_model().objects.create_user(
        email="testuser@example.com",
        password="TestPass123!",
    )
    return OrganizationUser.objects.create(user=user, org=org, role=role)


@pytest.fixture
def second_org(db):
    return Organization.objects.create(name="second-org")


@pytest.fixture
def second_org_user(db, second_org):
    role = Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)
    user = get_user_model().objects.create_user(
        email="testuser2@example.com",
        password="TestPass123!",
    )
    return OrganizationUser.objects.create(user=user, org=second_org, role=role)


@pytest.fixture
def mock_backend():
    return MagicMock(spec=AbstractStorageBackend)


@pytest.fixture
def storage_manager(mock_backend):
    return StorageManager(mock_backend)


@pytest.fixture
def sample_zip():
    """In-memory ZIP with two text files."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("hello.txt", "hello content")
        zf.writestr("sub/world.txt", "world content")
    buf.seek(0)
    buf.name = "sample.zip"
    return buf


@pytest.fixture
def sample_tar():
    """In-memory TAR with two text files."""
    buf = BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for name, content in [
            ("hello.txt", b"hello content"),
            ("sub/world.txt", b"world content"),
        ]:
            info = tarfile.TarInfo(name=name)
            info.size = len(content)
            tf.addfile(info, BytesIO(content))
    buf.seek(0)
    buf.name = "sample.tar"
    return buf


@pytest.fixture
def password_zip():
    """ZIP with password-protected (encrypted) entry flag set."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("secret.txt", "secret content")
    # Manually set the encryption flag bit on the first entry
    buf.seek(0)
    data = bytearray(buf.read())
    # Find the local file header flag field and set bit 0 (encrypted)
    # Local file header signature: PK\x03\x04 at offset 0
    # General purpose bit flag is at offset 6 from start of local header
    flag_offset = 6
    data[flag_offset] |= 0x01
    # Also update the central directory entry flag
    # Find central directory: PK\x01\x02
    cd_sig = b"PK\x01\x02"
    cd_offset = data.find(cd_sig)
    if cd_offset >= 0:
        cd_flag_offset = cd_offset + 8
        data[cd_flag_offset] |= 0x01
    buf = BytesIO(bytes(data))
    buf.seek(0)
    buf.name = "encrypted.zip"
    return buf


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_client(api_client, regular_user, default_org) -> APIClient:
    """Override the global `auth_client` for storage tests.

    `StorageAPIView` declares no `authentication_classes` of its own, and
    test settings clear `DEFAULT_AUTHENTICATION_CLASSES` — so a Bearer token
    is never processed and `request.user` stays `AnonymousUser` (same gap
    `tests/graph_collab/conftest.py` documents and works around for its own
    `auth_client`). `force_authenticate` bypasses authentication entirely.

    Uses the shared `regular_user`/`default_org` (not this module's own
    `org`/`org_user`, which back the lower-level backend/manager unit tests)
    because `test_storage_views.py` looks up the seeded "Default
    Organization" by name and creates graphs against it.
    """
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


@pytest.fixture
def superadmin_auth_client(api_client, superadmin_user, default_org) -> APIClient:
    """Authenticated client for the cross-org transfer path (superadmin-only).

    Same `force_authenticate` workaround as `auth_client` above — `StorageAPIView`
    has no `authentication_classes` of its own, and test settings clear
    `DEFAULT_AUTHENTICATION_CLASSES`, so a Bearer token is never processed and
    `request.user` stays `AnonymousUser`. On top of that, `_assert_cross_org_superadmin`
    (`tables/views/storage_views.py:79`) gates cross-org move/copy behind
    `request.user.is_superadmin`, so tests exercising that path need the shared
    `superadmin_user` fixture rather than `regular_user`.
    """
    api_client.force_authenticate(user=superadmin_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client
