import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tables.exceptions import (
    KeyValueEntryKeyInvalidError,
    KeyValueModeDeniedError,
    KeyValueEntryValueTooLargeError,
)
from tables.constants.key_value_constants import MAX_KEY_LENGTH
from tables.models import KeyValueTable, KeyValueTableEntry, Session

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
    assert service.delete(table, [key]) == 1


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
PERMITTED_MODES = {
    0: set(),
    R: {"read"},
    R | C: {"read"},
    R | U: {"read"},
    R | C | U: {"read", "write"},
    R | D: {"read", "delete"},
}
DENIED_MESSAGES = {
    "read": "You need Key-Value Tables View permission to configure a read node on the table "
    "'Acme customers'.",
    "write": "You need Key-Value Tables Create and Edit permission to configure a write node on "
    "the table 'Acme customers'.",
    "delete": "You need Key-Value Tables Delete permission to configure a delete node on the "
    "table 'Acme customers'.",
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
