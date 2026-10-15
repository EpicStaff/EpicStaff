import uuid

import pytest
from django.test import override_settings
from django.utils import timezone

from tables.exceptions import StorageQuotaExceeded
from tables.models import StorageFile
from tables.services.storage_service.dataclasses import BinPurgeGrant
from tables.services.storage_service.manager import StorageManager
from tables.services.storage_service.quota import (
    ensure_fits_quota,
    is_over_quota,
    org_free_bytes,
    org_used_bytes,
    org_writable_bytes,
    record_files_within_quota,
)
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from tests.storage_tests.in_memory_backend import InMemoryStorageBackend

pytestmark = pytest.mark.django_db

GRANT = BinPurgeGrant(actor="user 1")


@pytest.fixture
def recycle_bin():
    return StorageRecycleBinService(StorageManager(InMemoryStorageBackend()))


def _file_row(org, path: str, size: int | None, item_type: str = "file") -> None:
    StorageFile.objects.create(org=org, path=path, name=path, item_type=item_type, size=size)


def test_usage_sums_only_file_sizes(org):
    _file_row(org, "a", 100)
    _file_row(org, "d", None, item_type="folder")

    assert org_used_bytes(org.id) == 100


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_recording_within_quota_and_past_it(org, recycle_bin):
    _file_row(org, "a", 900)

    assert org_free_bytes(org.id) == 100
    assert (
        record_files_within_quota(
            org.id, [("b.txt", 50)], recycle_bin=recycle_bin, bin_purge=None
        )
        == []
    )
    assert StorageFile.objects.get(org=org, path="b.txt").size == 50
    with pytest.raises(StorageQuotaExceeded):
        record_files_within_quota(
            org.id, [("c.txt", 100)], recycle_bin=recycle_bin, bin_purge=None
        )


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_replacing_a_file_frees_its_bytes(org, recycle_bin):
    _file_row(org, "a", 900)

    assert org_free_bytes(org.id, replacing=["a"]) == 1000
    ensure_fits_quota(org.id, 100, bin_purge=None)
    with pytest.raises(StorageQuotaExceeded):
        ensure_fits_quota(org.id, 101, bin_purge=None)
    ensure_fits_quota(org.id, 1000, replacing=["a"], bin_purge=None)
    record_files_within_quota(org.id, [("a", 950)], recycle_bin=recycle_bin, bin_purge=None)
    assert StorageFile.objects.get(org=org, path="a").size == 950


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_is_over_quota_only_past_the_limit(org):
    _file_row(org, "a", 1000)
    assert not is_over_quota(org.id)

    _file_row(org, "b", 1)
    assert is_over_quota(org.id)


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_the_storage_bin_counts_as_freeable_only_under_a_grant(org):
    _file_row(org, "live", 700)
    StorageFile.all_objects.create(
        org=org,
        path="binned",
        name="binned",
        item_type="file",
        size=200,
        active=False,
        soft_deleted_at=timezone.now(),
        soft_delete_batch=uuid.uuid4(),
    )

    assert org_free_bytes(org.id) == 100
    assert org_writable_bytes(org.id, bin_purge=GRANT) == 300
    assert org_writable_bytes(org.id, bin_purge=None) == 100
    ensure_fits_quota(org.id, 300, bin_purge=GRANT)
    with pytest.raises(StorageQuotaExceeded):
        ensure_fits_quota(org.id, 301, bin_purge=GRANT)
    with pytest.raises(StorageQuotaExceeded):
        ensure_fits_quota(org.id, 101, bin_purge=None)


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_an_org_already_over_its_quota_has_nothing_writable(org):
    _file_row(org, "a", 1200)

    assert org_free_bytes(org.id) == 0
    assert org_writable_bytes(org.id, bin_purge=GRANT) == 0
