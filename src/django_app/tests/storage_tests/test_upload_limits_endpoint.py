from unittest.mock import MagicMock, patch

import pytest
from django.test import override_settings
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role
from tables.models import StorageFile
from tables.services.storage_service.archive.names import (
    ARCHIVE_SUFFIXES,
    DOCUMENT_EXTENSIONS,
    is_archive_name,
)

UPLOAD_LIMITS_URL = "/api/storage/upload-limits/"

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def no_object_storage():
    """StorageAPIView builds a storage manager per request; upload-limits never
    uses it, so no object storage is needed."""
    with patch("tables.views.storage_views.get_storage_manager", return_value=MagicMock()):
        yield


def _client_for(user, org=None) -> APIClient:
    client = APIClient()
    client.force_authenticate(user=user)
    if org is not None:
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


@pytest.mark.parametrize("max_file_size", [524288000, None], ids=["limited", "unlimited"])
def test_upload_limits_returns_the_configured_limits_and_the_free_space(org_user, max_file_size):
    with override_settings(
        MAX_STREAM_UPLOAD_FILE_SIZE=max_file_size,
        MAX_ARCHIVE_FILE_SIZE=52428800,
        ORG_STORAGE_QUOTA=1073741824,
    ):
        resp = _client_for(org_user.user, org_user.org).get(UPLOAD_LIMITS_URL)

    assert resp.status_code == status.HTTP_200_OK
    assert resp.json() == {
        "max_file_size": max_file_size,
        "max_archive_size": 52428800,
        "free_bytes": 1073741824,
        "archive_suffixes": sorted(ARCHIVE_SUFFIXES),
        "document_extensions": sorted(DOCUMENT_EXTENSIONS),
    }


@pytest.mark.parametrize(
    "filename", ["a.zip", "A.TAR.GZ", "b.tgz", "report.docx", "book.epub", "notes.txt", "x.jar"]
)
def test_the_returned_lists_classify_a_name_exactly_like_the_server(org_user, filename):
    # The contract a client mirrors: archive iff it ends with an archive suffix and
    # with no document extension.
    body = _client_for(org_user.user, org_user.org).get(UPLOAD_LIMITS_URL).json()
    lower = filename.lower()
    client_says_archive = any(lower.endswith(s) for s in body["archive_suffixes"]) and not any(
        lower.endswith(e) for e in body["document_extensions"]
    )

    assert client_says_archive == is_archive_name(filename)


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_free_bytes_counts_only_the_files_of_the_org_in_the_header(org_user, second_org_user):
    StorageFile.objects.create(org=org_user.org, path="a.bin", name="a.bin", item_type="file", size=300)
    StorageFile.objects.create(org=org_user.org, path="b.bin", name="b.bin", item_type="file", size=100)
    StorageFile.objects.create(org=second_org_user.org, path="c.bin", name="c.bin", item_type="file", size=50)

    own = _client_for(org_user.user, org_user.org).get(UPLOAD_LIMITS_URL)
    other = _client_for(second_org_user.user, second_org_user.org).get(UPLOAD_LIMITS_URL)

    assert own.json()["free_bytes"] == 600
    assert other.json()["free_bytes"] == 950


@override_settings(ORG_STORAGE_QUOTA=100)
def test_free_bytes_never_goes_below_zero(org_user):
    StorageFile.objects.create(org=org_user.org, path="a.bin", name="a.bin", item_type="file", size=150)

    resp = _client_for(org_user.user, org_user.org).get(UPLOAD_LIMITS_URL)

    assert resp.json()["free_bytes"] == 0


def test_an_anonymous_caller_gets_401(org):
    client = APIClient()
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))

    resp = client.get(UPLOAD_LIMITS_URL)

    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


def test_a_request_without_the_org_header_gets_400_org_context_required(org_user):
    resp = _client_for(org_user.user).get(UPLOAD_LIMITS_URL)

    assert resp.status_code == status.HTTP_400_BAD_REQUEST
    assert resp.json()["code"] == "org_context_required"


def test_a_viewer_may_read_the_upload_limits(viewer_org_user):
    resp = _client_for(viewer_org_user.user, viewer_org_user.org).get(UPLOAD_LIMITS_URL)

    assert resp.status_code == status.HTTP_200_OK


def test_a_role_without_files_read_gets_403(django_user_model, org):
    no_files_role = Role.objects.create(name="No files", org=org, is_built_in=False)
    user = django_user_model.objects.create_user(
        email="nofiles@example.com", password="TestPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=no_files_role)

    resp = _client_for(user, org).get(UPLOAD_LIMITS_URL)

    assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_a_caller_outside_the_header_org_is_refused_like_on_list(org_user, second_org):
    # The org in the header is resolved before any row is read, exactly as for the
    # other storage reads; the free space of an org the caller is not in never leaks.
    client = _client_for(org_user.user, second_org)

    limits = client.get(UPLOAD_LIMITS_URL)
    listing = client.get("/api/storage/list/", {"path": ""})

    assert limits.status_code == listing.status_code == status.HTTP_403_FORBIDDEN
    assert limits.json()["code"] == listing.json()["code"]
    assert "free_bytes" not in limits.json()
