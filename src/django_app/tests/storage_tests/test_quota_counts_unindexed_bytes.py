"""An organization's used storage is its StorageFile rows plus the bytes the store measurement
found without a row.

Run code writes straight to the store, so those bytes have no StorageFile row; the hourly
measurement records them as `OrganizationStorageUsage.unindexed_bytes`. Everything that reads
the quota sees them: the used and free bytes, the upload check, the upload-limits endpoint
and the refusal to mint storage credentials. Another organization's unindexed bytes never
count toward this one.
"""

from unittest.mock import MagicMock, patch

import pytest

from storage_credentials.services.session_credential_service import session_credential_service
from tables.exceptions import StorageQuotaExceeded
from tables.models import OrganizationStorageUsage, PythonCodeResult, StorageFile
from tables.services.run_admission import RunAdmissionRefusedError
from tables.services.storage_service.quota import (
    ensure_fits_quota,
    is_over_quota,
    org_free_bytes,
    org_used_bytes,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.services_tests.test_run_code_storage_credentials import gateway  # noqa: F401

pytestmark = pytest.mark.django_db

QUOTA = 1000


@pytest.fixture(autouse=True)
def small_quota(settings):
    settings.ORG_STORAGE_QUOTA = QUOTA


def _file_row(org, path: str, size: int) -> None:
    StorageFile.objects.create(org=org, path=path, name=path, item_type="file", size=size)


def _unindexed(org, size: int) -> None:
    OrganizationStorageUsage.objects.create(organization=org, unindexed_bytes=size)


@pytest.mark.parametrize(
    ("row_sizes", "unindexed", "used"),
    [
        ([300], None, 300),
        ([300], 0, 300),
        ([300], 200, 500),
        ([], 700, 700),
    ],
    ids=["never-measured", "measured-nothing-unindexed", "rows-and-unindexed", "unindexed-only"],
)
def test_used_bytes_are_the_rows_plus_the_unindexed_bytes(acme, row_sizes, unindexed, used):
    for index, size in enumerate(row_sizes):
        _file_row(acme, f"file-{index}", size)
    if unindexed is not None:
        _unindexed(acme, unindexed)

    assert org_used_bytes(acme.pk) == used


@pytest.mark.parametrize(("unindexed", "over"), [(400, False), (401, True)])
def test_unindexed_bytes_can_put_an_organization_over_its_quota(acme, unindexed, over):
    _file_row(acme, "rows", 600)
    _unindexed(acme, unindexed)

    assert is_over_quota(acme.pk) is over


def test_uploads_see_the_unindexed_bytes(acme, admin_client):
    _file_row(acme, "rows", 300)
    _unindexed(acme, 200)

    assert org_free_bytes(acme.pk) == 500
    ensure_fits_quota(acme.pk, 500, bin_purge=None)
    with pytest.raises(StorageQuotaExceeded):
        ensure_fits_quota(acme.pk, 501, bin_purge=None)
    with patch("tables.views.storage_views.get_storage_manager", return_value=MagicMock()):
        response = admin_client.get("/api/storage/upload-limits/")
    assert response.json()["free_bytes"] == 500


def _issue_for_test_run(org):
    result = PythonCodeResult.objects.create(execution_id=f"exec-{org.pk}", org=org)
    return session_credential_service.issue_for_test_run(
        python_code_result=result, storage_allowed_paths=["test-runs/x/"], org_id=org.pk
    )


def test_unindexed_bytes_alone_refuse_storage_credentials(gateway, acme):  # noqa: F811
    _unindexed(acme, QUOTA + 1)

    with pytest.raises(RunAdmissionRefusedError) as refusal:
        _issue_for_test_run(acme)

    assert refusal.value.default_code == "organization_storage_full"
    assert gateway.created == []


def test_another_organization_s_unindexed_bytes_never_count_here(gateway, acme, beta):  # noqa: F811
    _file_row(acme, "rows", 300)
    _unindexed(beta, QUOTA * 50)

    assert org_used_bytes(acme.pk) == 300
    assert _issue_for_test_run(acme).access_key == "temp-access-1"
