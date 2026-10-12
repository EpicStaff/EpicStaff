import pytest
from django.db import IntegrityError, connection, transaction

from rbac.authorship.registry import author_tracked_models
from rbac.models.org_scoped import OrgScopedModel
from tables.models import StorageFile
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _column_is_nullable(column: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = %s AND column_name = %s",
            [StorageFile._meta.db_table, column],
        )
        return cursor.fetchone()[0]


def _database_constraints() -> dict:
    with connection.cursor() as cursor:
        return connection.introspection.get_constraints(cursor, StorageFile._meta.db_table)


def test_storage_file_inherits_org_scoped_model():
    assert issubclass(StorageFile, OrgScopedModel)


def test_storage_file_is_released_with_other_authored_models():
    assert (StorageFile, "org_id") in author_tracked_models()


@pytest.mark.django_db
def test_org_column_stays_not_null_and_author_column_is_nullable():
    assert _column_is_nullable("org_id") == "NO"
    assert _column_is_nullable("created_by_id") == "YES"


@pytest.mark.django_db
def test_declared_indexes_exist_in_database():
    declared_fields = {tuple(index.fields) for index in StorageFile._meta.indexes}
    declared_names = {index.name for index in StorageFile._meta.indexes}

    assert declared_fields == {("org",), ("org", "path"), ("org", "parent_path")}
    assert declared_names <= set(_database_constraints())


@pytest.mark.django_db
def test_path_stays_unique_per_org(acme, beta):
    StorageFile.objects.create(org=acme, path="shared.txt", name="shared.txt")
    StorageFile.objects.create(org=beta, path="shared.txt", name="shared.txt")

    assert _database_constraints()["unique_storage_file_per_org"]["columns"] == [
        "org_id",
        "path",
    ]
    with pytest.raises(IntegrityError, match="unique_storage_file_per_org"), transaction.atomic():
        StorageFile.objects.create(org=acme, path="shared.txt", name="shared.txt")


@pytest.mark.django_db
def test_row_without_org_is_rejected_by_database():
    with pytest.raises(IntegrityError), transaction.atomic():
        StorageFile.objects.create(path="orgless.txt", name="orgless.txt")
