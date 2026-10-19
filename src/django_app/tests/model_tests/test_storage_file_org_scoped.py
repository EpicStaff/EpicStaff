import pytest
from django.db import IntegrityError, transaction

from tables.models import StorageFile
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.mark.django_db
def test_a_path_is_unique_within_an_org_but_free_across_orgs(acme, beta):
    StorageFile.objects.create(org=acme, path="shared.txt", name="shared.txt")
    StorageFile.objects.create(org=beta, path="shared.txt", name="shared.txt")

    # Only among live rows: a file in the recycle bin doesn't block a new one at its path.
    with (
        pytest.raises(IntegrityError, match="unique_active_storage_file_per_org"),
        transaction.atomic(),
    ):
        StorageFile.objects.create(org=acme, path="shared.txt", name="shared.txt")


@pytest.mark.django_db
def test_a_file_without_an_org_is_rejected_by_the_database():
    with pytest.raises(IntegrityError), transaction.atomic():
        StorageFile.objects.create(path="orgless.txt", name="orgless.txt")
