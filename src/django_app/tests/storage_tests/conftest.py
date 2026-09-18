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
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


@pytest.fixture
def fake_backend():
    """InMemoryStorageBackend standing in for S3StorageBackend, no org prefix."""
    return InMemoryStorageBackend(organization_prefix="")


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
