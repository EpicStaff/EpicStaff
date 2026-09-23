import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.exceptions import PersistenceKeyInvalidError, PersistenceValueTooLargeError
from tables.models import PersistenceTable, PersistenceTableEntry, Session
from tables.services.persistence_table_service import PersistenceTableService


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
