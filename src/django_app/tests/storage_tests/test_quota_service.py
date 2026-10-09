import pytest
from django.test import override_settings

from tables.exceptions import StorageQuotaExceeded
from tables.models import StorageFile
from tables.services.storage_service.quota import (
    ensure_fits_quota,
    is_over_quota,
    org_free_bytes,
    org_used_bytes,
    record_files_within_quota,
)

pytestmark = pytest.mark.django_db


def _file_row(org, path: str, size: int | None, item_type: str = "file") -> None:
    StorageFile.objects.create(org=org, path=path, name=path, item_type=item_type, size=size)


def test_usage_sums_only_file_sizes(org):
    _file_row(org, "a", 100)
    _file_row(org, "d", None, item_type="folder")

    assert org_used_bytes(org.id) == 100


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_recording_within_quota_and_past_it(org):
    _file_row(org, "a", 900)

    assert org_free_bytes(org.id) == 100
    record_files_within_quota(org.id, [("b.txt", 50)])
    assert StorageFile.objects.get(org=org, path="b.txt").size == 50
    with pytest.raises(StorageQuotaExceeded):
        record_files_within_quota(org.id, [("c.txt", 100)])


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_replacing_a_file_frees_its_bytes(org):
    _file_row(org, "a", 900)

    assert org_free_bytes(org.id, replacing=["a"]) == 1000
    ensure_fits_quota(org.id, 100)
    with pytest.raises(StorageQuotaExceeded):
        ensure_fits_quota(org.id, 101)
    ensure_fits_quota(org.id, 1000, replacing=["a"])
    record_files_within_quota(org.id, [("a", 950)])
    assert StorageFile.objects.get(org=org, path="a").size == 950


@override_settings(ORG_STORAGE_QUOTA=1000)
def test_is_over_quota_only_past_the_limit(org):
    _file_row(org, "a", 1000)
    assert not is_over_quota(org.id)

    _file_row(org, "b", 1)
    assert is_over_quota(org.id)
