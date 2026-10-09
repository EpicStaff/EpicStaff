import tarfile
import zipfile
from io import BytesIO
from unittest.mock import MagicMock

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from rbac.models import Organization, OrganizationUser
from rbac.models import Role
from tables.services.storage_service.upload import admission, archive_upload, file_upload
from tables.services.storage_service.base import AbstractStorageBackend
from tables.services.storage_service.manager import StorageManager
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend


@pytest.fixture(autouse=True)
def fresh_upload_admission(monkeypatch):
    """The upload gate is a per-worker singleton: rebuild it from each test's
    settings, and keep one test's in-flight uploads out of the next."""
    monkeypatch.setattr(admission, "_admission", None)


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
def viewer_org_user(db, org):
    """Org member whose role grants FILES:READ but not FILES:CREATE."""
    role = Role.objects.get(name="Viewer", is_built_in=True, org__isnull=True)
    user = get_user_model().objects.create_user(
        email="viewer@example.com",
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
def api_client():
    return APIClient()


@pytest.fixture
def stream_backend(monkeypatch, settings, backend):
    """Send every streamed upload to the test's in-memory `backend`, with room for any size."""
    settings.ORG_STORAGE_QUOTA = 10**9
    settings.MAX_STREAM_UPLOAD_FILE_SIZE = None
    monkeypatch.setattr(file_upload, "get_storage_backend", lambda **_: backend)
    monkeypatch.setattr(archive_upload, "get_storage_backend", lambda **_: backend)
    return backend
