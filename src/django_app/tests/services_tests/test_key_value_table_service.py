import re

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.exceptions import (
    KeyValueEntryKeyInvalidError,
    KeyValueModeDeniedError,
    KeyValueEntryValueTooLargeError,
    KeyValueTableNotFoundError,
)
from tables.constants.key_value_constants import MAX_KEY_LENGTH
from tables.models import Graph, KeyValueNode, KeyValueTable, KeyValueTableEntry, Session

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.services.key_value_table_service import KeyValueTableService
from rbac.exceptions import OrgMembershipRequiredError
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def table(default_org) -> KeyValueTable:
    return KeyValueTable.objects.create(org=default_org, name="Customers")


@pytest.fixture
def service() -> KeyValueTableService:
    return KeyValueTableService()


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
    created_at = KeyValueTableEntry.objects.get(table=table, key="a").created_at

    service.write(table, {"a": "new"}, session=session)

    entry = KeyValueTableEntry.objects.get(table=table, key="a")
    assert entry.value == "new"
    assert entry.updated_by_session_id == session.id
    assert entry.created_at == created_at
    assert entry.updated_at >= created_at


@pytest.mark.django_db
def test_write_returns_only_keys_that_did_not_exist(service, table):
    assert service.write(table, {"a": 1}) == ["a"]
    assert service.write(table, {"b": 2, "a": 3}) == ["b"]
    assert service.write(table, {"a": 4, "b": 5}) == []


@pytest.mark.django_db
def test_write_upserts_in_one_insert(service, table):
    service.write(table, {"a": 1})
    with CaptureQueriesContext(connection) as queries:
        service.write(table, {"a": 2, "b": 3})
    inserts = [q for q in queries.captured_queries if q["sql"].lstrip().upper().startswith("INSERT")]
    assert len(inserts) == 1
    assert "ON CONFLICT" in inserts[0]["sql"].upper()


@pytest.mark.django_db
def test_write_upserts_rows_in_key_order(service, table):
    with CaptureQueriesContext(connection) as queries:
        service.write(table, {"b": 1, "_z": 2, "B": 3, "a": 4})

    [insert] = [q["sql"] for q in queries.captured_queries if q["sql"].startswith("INSERT")]
    values = insert.split(" VALUES ", 1)[1].split(" ON CONFLICT", 1)[0]
    # Code-point ("C" collation) order, the order the delete locks rows in.
    assert re.findall(r"'(_z|B|a|b)'", values) == ["B", "_z", "a", "b"]


@pytest.mark.django_db
def test_write_locks_the_table_before_any_entry(service, table):
    service.write(table, {"a": 1})

    with CaptureQueriesContext(connection) as queries:
        service.write(table, {"a": 2, "b": 3})

    statements = [query["sql"] for query in queries.captured_queries]
    [lock_index] = [index for index, sql in enumerate(statements) if "FOR KEY SHARE" in sql]
    [insert_index] = [index for index, sql in enumerate(statements) if sql.startswith("INSERT")]
    first_entry_index = next(
        index for index, sql in enumerate(statements) if "tables_keyvaluetableentry" in sql
    )
    assert statements[lock_index] == (
        f'SELECT 1 FROM "tables_keyvaluetable" WHERE id = {table.pk} FOR KEY SHARE'
    )
    assert lock_index < first_entry_index <= insert_index
    assert statements[0].startswith("SAVEPOINT")
    assert statements[-1].startswith("RELEASE SAVEPOINT")


@pytest.mark.django_db
def test_write_to_a_table_deleted_meanwhile_is_not_found(service, table):
    stale = KeyValueTable.objects.get(pk=table.pk)
    KeyValueTable.objects.filter(pk=table.pk).delete()

    with pytest.raises(KeyValueTableNotFoundError):
        service.write(stale, {"a": 1})

    assert not KeyValueTableEntry.objects.filter(table_id=table.pk).exists()


@pytest.mark.django_db
def test_write_rejects_oversized_value(service, table):
    with pytest.raises(KeyValueEntryValueTooLargeError):
        service.write(table, {"big": "x" * (256 * 1024)})
    assert not KeyValueTableEntry.objects.filter(table=table).exists()


# Keep identical to the resolved-key parity table in crew tests/graph/test_key_value_node.py.
VALID_RESOLVED_KEYS = ["k", "_", "user_42", "a" * 512]
INVALID_RESOLVED_KEYS = [
    "",
    "4_user",
    "user_4 2",
    "user_-1",
    "user_1.5",
    "user_é",
    "a{b}",
    "k\n",
    "a" * 513,
]


@pytest.mark.django_db
@pytest.mark.parametrize("key", VALID_RESOLVED_KEYS)
def test_valid_resolved_keys_are_written_read_and_deleted(service, table, key):
    assert service.write(table, {key: 1}) == [key]
    assert service.read(table, [key]) == {key: 1}
    assert service.delete(table, [key]) == {key: 1}


@pytest.mark.django_db
@pytest.mark.parametrize("bad_key", INVALID_RESOLVED_KEYS)
def test_write_rejects_invalid_key(service, table, bad_key):
    with pytest.raises(KeyValueEntryKeyInvalidError) as error:
        service.write(table, {"good": 1, bad_key: 1})
    shown = bad_key if len(bad_key) <= 100 else f"{bad_key[:100]}…"
    assert str(error.value.detail) == (
        f"Key {shown!r} is not a valid key: use only letters, digits and _, don't start with a "
        "digit, and keep it to at most 512 characters."
    )
    assert not KeyValueTableEntry.objects.filter(table=table).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("operation", ["read", "delete"])
@pytest.mark.parametrize("bad_key", INVALID_RESOLVED_KEYS)
def test_read_and_delete_reject_invalid_key(service, table, operation, bad_key):
    # An old row whose key predates the rule; the column cannot hold a longer key at all.
    KeyValueTableEntry.objects.create(table=table, key=bad_key[:MAX_KEY_LENGTH], value=1)

    with pytest.raises(KeyValueEntryKeyInvalidError):
        getattr(service, operation)(table, ["good", bad_key])

    assert KeyValueTableEntry.objects.filter(table=table).count() == 1


@pytest.mark.django_db
def test_delete_returns_deleted_values_without_missing_keys(service, table):
    service.write(table, {"a": {"name": "Ann", "tags": [1]}, "b": 2, "stored_null": None})

    deleted = service.delete(table, ["a", "missing", "stored_null"])

    assert deleted == {"a": {"name": "Ann", "tags": [1]}, "stored_null": None}
    assert service.read(table, ["a", "b", "stored_null"]) == {"b": 2}


@pytest.mark.django_db
def test_delete_leaves_other_tables_untouched(service, table, default_org):
    other = KeyValueTable.objects.create(org=default_org, name="Other")
    service.write(other, {"a": "theirs"})
    service.write(table, {"a": "ours"})

    assert service.delete(table, ["a"]) == {"a": "ours"}
    assert service.read(other, ["a"]) == {"a": "theirs"}


@pytest.mark.django_db
def test_delete_locks_reads_and_deletes_the_same_rows_in_one_transaction(service, table):
    service.write(table, {"a": 1, "b": 2})
    locked_ids = set(KeyValueTableEntry.objects.filter(table=table).values_list("pk", flat=True))

    with CaptureQueriesContext(connection) as queries:
        assert service.delete(table, ["a", "b"]) == {"a": 1, "b": 2}

    statements = [query["sql"] for query in queries.captured_queries]
    # pytest-django already runs the test in a transaction, so the service's atomic block
    # shows up as a savepoint around the lock and the delete.
    assert statements[0].startswith("SAVEPOINT")
    assert statements[-1].startswith("RELEASE SAVEPOINT")
    [select, delete] = statements[1:-1]
    assert select.startswith("SELECT") and select.endswith("FOR UPDATE")
    # Locked in the one order every multi-row writer uses, so two requests cannot deadlock.
    assert re.search(r'ORDER BY "tables_keyvaluetableentry"\."key" COLLATE "C" ASC FOR UPDATE$', select)
    # Deleted by the locked primary keys, not by key again: a row written under the same
    # key after the lock could not be the one reported.
    delete_where = delete.split(" WHERE ", 1)[1]
    [deleted_ids] = re.findall(r'"tables_keyvaluetableentry"\."id" IN \(([^)]*)\)', delete_where)
    assert {int(pk) for pk in deleted_ids.split(",")} == locked_ids
    assert '"key"' not in delete_where
    assert not KeyValueTableEntry.objects.filter(table=table).exists()


@pytest.mark.django_db
def test_delete_of_only_missing_keys_issues_no_delete(service, table):
    with CaptureQueriesContext(connection) as queries:
        assert service.delete(table, ["missing"]) == {}

    assert not any(query["sql"].startswith("DELETE") for query in queries.captured_queries)


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


@pytest.mark.django_db
def test_with_value_preview_defers_value(service, table):
    service.write(table, {"k": {"a": 1}})

    entry = service.with_value_preview(KeyValueTableEntry.objects.filter(table=table)).get()

    assert entry.get_deferred_fields() == {"value"}
    assert (entry.value_preview, entry.value_truncated) == ('{"a": 1}', False)


@pytest.mark.django_db
@pytest.mark.parametrize(("characters", "truncated"), [(198, False), (199, True)])
def test_with_value_preview_truncates_past_200_json_characters(service, table, characters, truncated):
    # A string's JSON text is the string plus its two quotes: 198 characters render as 200.
    service.write(table, {"k": "x" * characters})

    entry = service.with_value_preview(KeyValueTableEntry.objects.filter(table=table)).get()

    assert entry.value_preview == ('"' + "x" * characters + '"')[:200]
    assert entry.value_truncated is truncated


@pytest.fixture
def acme_table(acme) -> KeyValueTable:
    return KeyValueTable.objects.create(org=acme, name="Acme customers")


def _acme_user(django_user_model, acme, bits: int):
    role = Role.objects.create(name=f"Key-Value tables {bits}", org=acme, is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ResourceType.KEY_VALUE_TABLES, permissions=bits
    )
    user = django_user_model.objects.create_user(
        email=f"key-value-tables-{bits}@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


R = int(Permission.READ)
C = int(Permission.CREATE)
U = int(Permission.UPDATE)
D = int(Permission.DELETE)

# bits -> the modes they may configure. Write needs C and U: C or U alone is not enough.
# Delete needs R and D: D alone would let a delete node reveal values the role cannot view.
PERMITTED_MODES = {
    0: set(),
    R: {"read"},
    R | C: {"read"},
    R | U: {"read"},
    R | C | U: {"read", "write"},
    D: set(),
    R | D: {"read", "delete"},
}
DENIED_MESSAGES = {
    "read": "You need Key-Value Tables View permission to configure a read node on the table "
    "'Acme customers'.",
    "write": "You need Key-Value Tables Create and Edit permission to configure a write node on "
    "the table 'Acme customers'.",
    "delete": "You need Key-Value Tables View and Delete permission to configure a delete node "
    "on the table 'Acme customers'.",
}


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
@pytest.mark.parametrize("bits", list(PERMITTED_MODES))
def test_assert_can_configure_needs_every_permission_of_the_mode(
    service, acme_table, acme, django_user_model, bits, mode
):
    user = _acme_user(django_user_model, acme, bits)
    permitted = mode in PERMITTED_MODES[bits]

    assert service.can_configure(user, acme_table, mode) is permitted
    if permitted:
        service.assert_can_configure(user, acme_table, mode)
    else:
        with pytest.raises(KeyValueModeDeniedError) as error:
            service.assert_can_configure(user, acme_table, mode)
        assert str(error.value.detail) == DENIED_MESSAGES[mode]
        assert error.value.get_codes() == "key_value_mode_denied"


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
def test_assert_can_configure_denies_member_of_another_org(service, beta, admin_acme, mode):
    beta_table = KeyValueTable.objects.create(org=beta, name="Beta customers")

    with pytest.raises(OrgMembershipRequiredError):
        service.assert_can_configure(admin_acme, beta_table, mode)
    assert service.can_configure(admin_acme, beta_table, mode) is False


@pytest.mark.django_db
@pytest.mark.parametrize("mode", ["read", "write", "delete"])
def test_resolve_reference_binds_only_with_mode_permissions(
    service, acme_table, acme, django_user_model, mode
):
    user = _acme_user(django_user_model, acme, R)

    resolved = service.resolve_reference(
        acme.id, acme_table.id, acme_table.name, mode=mode, user=user
    )

    assert resolved == (acme_table if mode == "read" else None)


@pytest.mark.django_db
def test_delete_table_unlinks_its_nodes(service, table, graph):
    node = KeyValueNode.objects.create(graph=graph, node_name="p", key_value_table=table)
    KeyValueTableEntry.objects.create(table=table, key="k", value=1)

    service.delete_table(table)

    assert not KeyValueTable.objects.filter(pk=table.pk).exists()
    node.refresh_from_db()
    assert node.key_value_table_id is None


@pytest.mark.django_db
def test_delete_table_already_deleted_meanwhile_is_not_found(service, table):
    # What a second DELETE sees once the first one, which held the row lock, has committed.
    stale = KeyValueTable.objects.get(pk=table.pk)
    KeyValueTable.objects.filter(pk=table.pk).delete()

    with pytest.raises(KeyValueTableNotFoundError) as error:
        service.delete_table(stale)

    assert error.value.status_code == 404
    assert error.value.default_code == "key_value_table_not_found"


@pytest.mark.django_db
def test_usage_counts_live_nodes_and_distinct_flows(service, table, default_org):
    first = Graph.objects.create(name="First", org=default_org)
    second = Graph.objects.create(name="Second", org=default_org)
    KeyValueNode.objects.create(graph=first, node_name="a", key_value_table=table)
    KeyValueNode.objects.create(graph=first, node_name="b", key_value_table=table)
    KeyValueNode.objects.create(graph=second, node_name="c", key_value_table=table)

    assert service.usage(table) == {"node_count": 3, "flow_count": 2}
