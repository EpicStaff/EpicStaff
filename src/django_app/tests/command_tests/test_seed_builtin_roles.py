import copy
import json
from io import StringIO

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.core.management.base import CommandError

from rbac.access import builtin_roles
from rbac.access.audit_history import AUDIT_HISTORY_DAYS_MAX
from rbac.access.builtin_roles import BUILTIN_ROLES_PATH, BuiltInRoleSeeder
from rbac.models import Role, RoleAuditPolicy, RolePermission
from rbac.models.enums import BuiltInRole, Permission

SHIPPED = json.loads(BUILTIN_ROLES_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def roles_file(tmp_path_factory):
    """Write an edited copy of the shipped definition (or raw text) and return its path.

    `tmp_path_factory`, not `tmp_path`: conftest overrides `tmp_path` with a shared dir.
    """

    def write(edit=None, raw=None):
        definition = copy.deepcopy(SHIPPED)
        if edit is not None:
            edit(definition)
        path = tmp_path_factory.mktemp("builtin_roles") / "builtin_roles.json"
        path.write_text(json.dumps(definition) if raw is None else raw, encoding="utf-8")
        return path

    return write


@pytest.fixture
def seeded(db):
    BuiltInRoleSeeder().seed()


def _mask(role_name, resource_type):
    row = RolePermission.objects.filter(
        role__name=role_name,
        role__is_built_in=True,
        role__org__isnull=True,
        resource_type=resource_type,
    ).first()
    return None if row is None else row.permissions


def _snapshot():
    roles = Role.objects.filter(is_built_in=True, org__isnull=True)
    return (
        sorted(roles.values_list("name", "description")),
        sorted(
            RolePermission.objects.filter(role__in=roles).values_list(
                "role__name", "resource_type", "permissions"
            )
        ),
    )


def _grant(role_name, resource_type, actions):
    def edit(definition):
        definition[role_name]["permissions"][resource_type] = actions

    return edit


@pytest.mark.django_db
def test_shipped_file_is_valid():
    BuiltInRoleSeeder().seed()


@pytest.mark.django_db
def test_second_run_changes_nothing(seeded):
    assert BuiltInRoleSeeder().seed().changes == []


@pytest.mark.django_db
def test_removing_an_action_revokes_it(seeded, roles_file):
    path = roles_file(_grant(BuiltInRole.MEMBER, "flows", ["create", "read"]))

    result = BuiltInRoleSeeder(path).seed()

    assert _mask(BuiltInRole.MEMBER, "flows") == Permission.CREATE | Permission.READ
    assert result.changes == ["Member.flows: create, read, update (7) -> create, read (3)"]


@pytest.mark.django_db
def test_removing_a_resource_deletes_its_row(seeded, roles_file):
    def edit(definition):
        del definition[BuiltInRole.MEMBER]["permissions"]["webhooks"]

    result = BuiltInRoleSeeder(roles_file(edit)).seed()

    assert _mask(BuiltInRole.MEMBER, "webhooks") is None
    assert result.changes == ["Member.webhooks: removed create, read, update, delete (15)"]


@pytest.mark.django_db
def test_granting_creates_a_row_and_widens_a_mask(seeded, roles_file):
    def edit(definition):
        definition[BuiltInRole.VIEWER]["permissions"]["secrets"] = ["read"]
        definition[BuiltInRole.VIEWER]["permissions"]["flows"] = ["read", "export"]

    result = BuiltInRoleSeeder(roles_file(edit)).seed()

    assert _mask(BuiltInRole.VIEWER, "secrets") == Permission.READ
    assert _mask(BuiltInRole.VIEWER, "flows") == Permission.READ | Permission.EXPORT
    assert "Viewer.secrets: granted read (2)" in result.changes


@pytest.mark.django_db
def test_a_dead_bit_in_the_database_is_cleared(seeded):
    RolePermission.objects.filter(
        role__name=BuiltInRole.VIEWER, role__is_built_in=True, resource_type="flows"
    ).update(permissions=66)

    result = BuiltInRoleSeeder().seed()

    assert _mask(BuiltInRole.VIEWER, "flows") == Permission.READ
    assert result.changes == ["Viewer.flows: read (66) -> read (2)"]


@pytest.mark.django_db
def test_a_missing_role_is_created_with_its_permissions(seeded):
    Role.objects.filter(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True).delete()

    result = BuiltInRoleSeeder().seed()

    role = Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)
    assert role.description == SHIPPED[BuiltInRole.VIEWER]["description"]
    assert _mask(BuiltInRole.VIEWER, "flows") == Permission.READ
    assert result.changes[0] == "Viewer: created"


@pytest.mark.django_db
def test_description_drift_is_corrected(seeded):
    Role.objects.filter(name=BuiltInRole.VIEWER, is_built_in=True).update(description="stale")

    result = BuiltInRoleSeeder().seed()

    viewer = Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)
    assert viewer.description == SHIPPED[BuiltInRole.VIEWER]["description"]
    assert result.changes == ["Viewer: description updated"]


@pytest.mark.django_db
def test_a_built_in_role_missing_from_the_file_is_kept(seeded):
    legacy = Role.objects.create(name="Legacy", is_built_in=True, org=None)

    result = BuiltInRoleSeeder().seed()

    assert Role.objects.filter(pk=legacy.pk).exists()
    assert result.warnings == ["Legacy: built-in role not in builtin_roles.json; left untouched"]


@pytest.mark.django_db
def test_a_duplicate_built_in_row_is_warned_about(seeded):
    Role.objects.create(name=BuiltInRole.VIEWER, is_built_in=True, org=None)

    result = BuiltInRoleSeeder().seed()

    assert (
        "Viewer: 2 built-in rows share this name; only the lowest id is reconciled"
        in result.warnings
    )


def _history_days(role_name, value):
    def edit(definition):
        definition[role_name]["audit_history_days"] = value

    return edit


def _org_admin_history_days():
    policy = RoleAuditPolicy.objects.filter(
        role__name=BuiltInRole.ORG_ADMIN, role__is_built_in=True, role__org__isnull=True
    ).first()
    return None if policy is None else policy.history_days


@pytest.mark.django_db
def test_audit_history_days_creates_updates_and_deletes_the_policy(seeded, roles_file):
    org_admin = BuiltInRole.ORG_ADMIN

    created = BuiltInRoleSeeder(roles_file(_history_days(org_admin, 30))).seed()
    assert _org_admin_history_days() == 30
    assert created.changes == [f"{org_admin}.audit_history_days: unlimited -> 30"]

    unchanged = BuiltInRoleSeeder(roles_file(_history_days(org_admin, 30))).seed()
    assert unchanged.changes == []

    updated = BuiltInRoleSeeder(roles_file(_history_days(org_admin, 60))).seed()
    assert _org_admin_history_days() == 60
    assert updated.changes == [f"{org_admin}.audit_history_days: 30 -> 60"]

    removed = BuiltInRoleSeeder().seed()
    assert _org_admin_history_days() is None
    assert removed.changes == [f"{org_admin}.audit_history_days: 60 -> unlimited"]


INVALID = {
    "unknown resource": _grant(BuiltInRole.MEMBER, "widgets", ["read"]),
    "action not applicable": _grant(BuiltInRole.VIEWER, "flows", ["read", "use"]),
    "platform action": _grant(BuiltInRole.ORG_ADMIN, "organizations", ["read", "create"]),
    "reserved list action": _grant(BuiltInRole.VIEWER, "secrets", ["list"]),
    "empty action list": _grant(BuiltInRole.VIEWER, "flows", []),
    "duplicate action": _grant(BuiltInRole.VIEWER, "flows", ["read", "read"]),
    "superadmin grant": _grant(BuiltInRole.SUPERADMIN, "flows", ["read"]),
    "missing role": lambda definition: definition.pop(BuiltInRole.VIEWER),
    "unknown role": lambda definition: definition.update(
        {"Guest": {"description": "Guest", "permissions": {}}}
    ),
    "extra role key": lambda definition: definition[BuiltInRole.MEMBER].update({"color": "blue"}),
    "missing description": lambda definition: definition[BuiltInRole.MEMBER].pop("description"),
    "blank description": lambda definition: definition[BuiltInRole.MEMBER].update(
        {"description": " "}
    ),
    "history limit without audit": _history_days(BuiltInRole.MEMBER, 30),
    "history limit on superadmin": _history_days(BuiltInRole.SUPERADMIN, 30),
    "history limit zero": _history_days(BuiltInRole.ORG_ADMIN, 0),
    "history limit bool": _history_days(BuiltInRole.ORG_ADMIN, True),
    "history limit string": _history_days(BuiltInRole.ORG_ADMIN, "30"),
    "history limit above max": _history_days(BuiltInRole.ORG_ADMIN, AUDIT_HISTORY_DAYS_MAX + 1),
}


@pytest.mark.django_db
@pytest.mark.parametrize("edit", list(INVALID.values()), ids=list(INVALID))
def test_an_invalid_file_is_rejected_without_writing(seeded, roles_file, edit):
    path = roles_file(edit)
    # A pending change the valid parts of the file would apply: proves nothing is half-written.
    Role.objects.filter(name=BuiltInRole.VIEWER, is_built_in=True).update(description="stale")
    before = _snapshot()

    with pytest.raises(ImproperlyConfigured):
        BuiltInRoleSeeder(path).seed()

    assert _snapshot() == before


def _duplicated_member_permission():
    member_permissions = json.dumps(SHIPPED[BuiltInRole.MEMBER]["permissions"])
    return json.dumps(SHIPPED).replace(member_permissions, member_permissions[:-1] + ', "flows": ["read"]}', 1)


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("{not json", "Cannot read"),
        ("[]", "expected an object"),
        (json.dumps(SHIPPED)[:-1] + ', "Viewer": {"description": "x", "permissions": {}}}', "duplicate key 'Viewer'"),
        (_duplicated_member_permission(), "duplicate key 'flows'"),
    ],
    ids=["not-json", "not-an-object", "duplicate-role", "duplicate-resource"],
)
def test_an_unreadable_file_is_rejected(roles_file, raw, message):
    with pytest.raises(ImproperlyConfigured, match=message):
        BuiltInRoleSeeder(roles_file(raw=raw)).seed()


def test_every_error_is_reported_at_once(roles_file):
    def edit(definition):
        definition[BuiltInRole.MEMBER]["permissions"]["widgets"] = ["read"]
        definition[BuiltInRole.VIEWER]["permissions"]["flows"] = ["use"]

    with pytest.raises(ImproperlyConfigured) as error:
        BuiltInRoleSeeder(roles_file(edit)).seed()

    assert "Member.widgets" in str(error.value)
    assert "Viewer.flows" in str(error.value)


@pytest.mark.django_db
def test_command_reports_up_to_date(seeded):
    out = StringIO()

    call_command("seed_builtin_roles", stdout=out)

    assert "Built-in roles up to date." in out.getvalue()


@pytest.mark.django_db
def test_command_prints_each_change(seeded):
    Role.objects.filter(name=BuiltInRole.VIEWER, is_built_in=True).update(description="stale")
    out = StringIO()

    call_command("seed_builtin_roles", stdout=out)

    assert "Viewer: description updated" in out.getvalue()
    assert "Built-in roles updated: 1 change(s)." in out.getvalue()


@pytest.mark.django_db
def test_command_warns_about_an_unlisted_built_in_role(seeded):
    Role.objects.create(name="Legacy", is_built_in=True, org=None)
    err = StringIO()

    call_command("seed_builtin_roles", stdout=StringIO(), stderr=err)

    assert "Legacy" in err.getvalue()


@pytest.mark.django_db
def test_command_fails_on_an_invalid_file(seeded, roles_file, monkeypatch):
    monkeypatch.setattr(builtin_roles, "BUILTIN_ROLES_PATH", roles_file(raw="[]"))

    with pytest.raises(CommandError, match="expected an object"):
        call_command("seed_builtin_roles")
