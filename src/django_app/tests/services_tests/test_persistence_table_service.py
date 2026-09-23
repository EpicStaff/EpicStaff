import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.exceptions import PersistenceKeyInvalidError, PersistenceValueTooLargeError
from tables.models import PersistenceTable, PersistenceTableEntry, Session
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models import OrganizationUser
from tables.services.persistence_table_service import PersistenceTableService
from tables.services.rbac.rbac_exceptions import OrgMembershipRequiredError
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def table(default_org) -> PersistenceTable:
    return PersistenceTable.objects.create(org=default_org, name="Customers")


@pytest.fixture
def service() -> PersistenceTableService:
    return PersistenceTableService()


@pytest.mark.django_db
def test_write_then_read_returns_only_stored_keys(service, table):
    service.write(table, {"a": 1, "b": {"nested": [1, 2]}, "c": None})
    assert service.read(table, ["a", "b", "c", "missing"]) == {
        "a": 1,
        "b": {"nested": [1, 2]},
        "c": None,
    }


@pytest.mark.django_db
def test_write_overwrites_existing_key_and_records_session(service, table, graph):
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)
    service.write(table, {"a": "old"})
    created_at = PersistenceTableEntry.objects.get(table=table, key="a").created_at

    service.write(table, {"a": "new"}, session=session)

    entry = PersistenceTableEntry.objects.get(table=table, key="a")
    assert entry.value == "new"
    assert entry.updated_by_session_id == session.id
    assert entry.created_at == created_at
    assert entry.updated_at >= created_at


@pytest.mark.django_db
def test_write_is_single_statement_upsert(service, table):
    service.write(table, {"a": 1})
    with CaptureQueriesContext(connection) as queries:
        service.write(table, {"a": 2, "b": 3})
    inserts = [q for q in queries.captured_queries if q["sql"].lstrip().upper().startswith("INSERT")]
    assert len(inserts) == 1
    assert "ON CONFLICT" in inserts[0]["sql"].upper()


@pytest.mark.django_db
def test_write_rejects_oversized_value(service, table):
    with pytest.raises(PersistenceValueTooLargeError):
        service.write(table, {"big": "x" * (256 * 1024)})
    assert not PersistenceTableEntry.objects.filter(table=table).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("bad_key", ["", "k" * 513])
def test_write_rejects_invalid_key(service, table, bad_key):
    with pytest.raises(PersistenceKeyInvalidError):
        service.write(table, {bad_key: 1})


@pytest.mark.django_db
def test_delete_removes_keys_and_ignores_missing(service, table):
    service.write(table, {"a": 1, "b": 2})
    assert service.delete(table, ["a", "missing"]) == 1
    assert service.read(table, ["a", "b"]) == {"b": 2}


@pytest.mark.django_db
def test_lookup_reports_existence_and_truncated_preview(service, table):
    service.write(table, {"long": "y" * 500, "short": {"k": "v"}})
    result = service.lookup(table, ["long", "short", "missing"])

    assert result["long"].exists is True
    assert len(result["long"].value_preview) == 200
    assert result["short"].value_preview == '{"k": "v"}'
    assert result["short"].updated_at is not None
    assert result["missing"].exists is False
    assert result["missing"].value_preview is None
    assert result["missing"].updated_at is None


@pytest.fixture
def acme_table(acme) -> PersistenceTable:
    return PersistenceTable.objects.create(org=acme, name="Acme customers")


@pytest.mark.django_db
def test_assert_can_use_allows_member(service, acme_table, member_only):
    service.assert_can_use(member_only, acme_table)


@pytest.mark.django_db
def test_assert_can_use_denies_viewer(service, acme_table, acme, role_viewer, django_user_model):
    viewer = django_user_model.objects.create_user(
        email="viewer-persistence@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=viewer, org=acme, role=role_viewer)

    with pytest.raises(PermissionDenied):
        service.assert_can_use(viewer, acme_table)


@pytest.mark.django_db
def test_assert_can_use_denies_member_of_another_org(service, beta, member_only):
    beta_table = PersistenceTable.objects.create(org=beta, name="Beta customers")

    with pytest.raises(OrgMembershipRequiredError):
        service.assert_can_use(member_only, beta_table)
