import pytest
from django.test import override_settings

from tables.models import Organization, StorageFile
from tables.exceptions import StorageQuotaExceeded
from tables.services.storage_service.quota_service import (
    ensure_fits_quota,
    is_over_quota,
    org_free_bytes,
    org_used_bytes,
    record_files_within_quota,
)


@pytest.mark.django_db
def test_usage_sums_only_file_sizes():
    org = Organization.objects.create(name="Acme")
    StorageFile.objects.create(org=org, path="a", name="a", item_type="file", size=100)
    StorageFile.objects.create(org=org, path="d", name="d", item_type="folder", size=None)
    assert org_used_bytes(org.id) == 100


@pytest.mark.django_db
@override_settings(ORG_STORAGE_QUOTA=1000)
def test_free_bytes_and_recording_within_quota():
    org = Organization.objects.create(name="Acme")
    StorageFile.objects.create(org=org, path="a", name="a", item_type="file", size=900)
    assert org_free_bytes(org.id) == 100
    record_files_within_quota(org.id, [("b.txt", 50)])
    assert StorageFile.objects.get(org=org, path="b.txt").size == 50
    with pytest.raises(StorageQuotaExceeded):
        record_files_within_quota(org.id, [("c.txt", 100)])


@pytest.mark.django_db
@override_settings(ORG_STORAGE_QUOTA=1000)
def test_replacing_a_file_frees_its_bytes():
    org = Organization.objects.create(name="Acme")
    StorageFile.objects.create(org=org, path="a", name="a", item_type="file", size=900)
    assert org_free_bytes(org.id, replacing=["a"]) == 1000
    record_files_within_quota(org.id, [("a", 950)])
    assert StorageFile.objects.get(org=org, path="a").size == 950


@pytest.mark.django_db
@override_settings(ORG_STORAGE_QUOTA=1000)
def test_ensure_fits_quota_counts_replaced_files_as_freed():
    org = Organization.objects.create(name="Acme")
    StorageFile.objects.create(org=org, path="a", name="a", item_type="file", size=900)
    ensure_fits_quota(org.id, 100)
    with pytest.raises(StorageQuotaExceeded):
        ensure_fits_quota(org.id, 101)
    ensure_fits_quota(org.id, 1000, replacing=["a"])


@pytest.mark.django_db
@override_settings(ORG_STORAGE_QUOTA=1000)
def test_is_over_quota_only_past_the_limit():
    org = Organization.objects.create(name="Acme")
    StorageFile.objects.create(org=org, path="a", name="a", item_type="file", size=1000)
    assert not is_over_quota(org.id)
    StorageFile.objects.create(org=org, path="b", name="b", item_type="file", size=1)
    assert is_over_quota(org.id)
