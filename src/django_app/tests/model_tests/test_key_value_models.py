import pytest
from django.db import IntegrityError, transaction

from tables.models import KeyValueTable, KeyValueTableEntry
from rbac.models import Organization


@pytest.fixture
def other_org(db) -> Organization:
    return Organization.objects.create(name="Other org")


@pytest.mark.django_db
def test_table_name_is_unique_per_org_case_insensitive(default_org):
    KeyValueTable.objects.create(org=default_org, name="Customers")
    with pytest.raises(IntegrityError), transaction.atomic():
        KeyValueTable.objects.create(org=default_org, name="customers")


@pytest.mark.django_db
def test_same_table_name_allowed_in_another_org(default_org, other_org):
    KeyValueTable.objects.create(org=default_org, name="Customers")
    KeyValueTable.objects.create(org=other_org, name="Customers")
    assert KeyValueTable.objects.filter(name="Customers").count() == 2


@pytest.mark.django_db
def test_table_requires_org():
    with pytest.raises(IntegrityError), transaction.atomic():
        KeyValueTable.objects.create(org=None, name="Orphan")


@pytest.mark.django_db
def test_entry_key_is_unique_per_table(default_org):
    table = KeyValueTable.objects.create(org=default_org, name="T")
    KeyValueTableEntry.objects.create(table=table, key="a", value=1)
    with pytest.raises(IntegrityError), transaction.atomic():
        KeyValueTableEntry.objects.create(table=table, key="a", value=2)


@pytest.mark.django_db
def test_deleting_table_deletes_entries(default_org):
    table = KeyValueTable.objects.create(org=default_org, name="T")
    KeyValueTableEntry.objects.create(table=table, key="a", value={"x": 1})
    table.delete()
    assert KeyValueTableEntry.objects.count() == 0
