"""The audit history limit on the role-admin API.

The limit travels inside the `audit` entry of a role's `permissions` list
(0 or omitted = unlimited). It is stored as a `RoleAuditPolicy` row, absent when
unlimited, and the escalation ceiling covers it.
"""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from rbac.access.audit_history import AUDIT_HISTORY_DAYS_MAX
from rbac.models import OrganizationUser, Role, RoleAuditPolicy, RolePermission
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ROLES_URL = "/api/admin/roles/"
CRUD = int(Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE)


def _detail_url(role):
    return f"{ROLES_URL}{role.id}/"


def _audit_entry(history_days=None, actions=("read", "export")):
    entry = {"resource_type": "audit", "actions": list(actions)}
    if history_days is not None:
        entry["audit_history_days"] = history_days
    return entry


def _entry(body, resource_type):
    return next(entry for entry in body["permissions"] if entry["resource_type"] == resource_type)


def _policy_days(role_id):
    policy = RoleAuditPolicy.objects.filter(role_id=role_id).first()
    return None if policy is None else policy.history_days


def _audit_role(org, name, history_days=None, extra=()):
    """A custom role that reads and exports audit, with an optional policy row."""
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.AUDIT,
        permissions=int(Permission.READ | Permission.EXPORT),
    )
    for resource_type, mask in extra:
        RolePermission.objects.create(role=role, resource_type=resource_type, permissions=mask)
    if history_days is not None:
        RoleAuditPolicy.objects.create(role=role, history_days=history_days)
    return role


@pytest.fixture
def limited_role_manager(db, django_user_model, acme):
    """Manages roles in Acme and reads audit, but only 30 days back."""
    role = _audit_role(acme, "Limited role manager", history_days=30, extra=[("roles", CRUD)])
    user = django_user_model.objects.create_user(
        email="limited-role-manager@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=acme, role=role)
    return user


# ---- create ----


@pytest.mark.django_db
def test_create_with_a_limit_stores_it_and_shows_it_on_the_audit_entry(client_as, admin_acme, acme):
    response = client_as(admin_acme).post(
        ROLES_URL,
        {
            "org_id": acme.id,
            "name": "Compliance reviewer",
            "permissions": [_audit_entry(30), {"resource_type": "flows", "actions": ["read"]}],
        },
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    body = response.json()
    assert _entry(body, "audit") == {
        "resource_type": "audit",
        "actions": ["read", "export"],
        "audit_history_days": 30,
    }
    assert "audit_history_days" not in _entry(body, "flows")
    assert "audit_history_days" not in body
    assert _policy_days(body["id"]) == 30


@pytest.mark.django_db
def test_create_with_audit_and_no_limit_is_unlimited(client_as, admin_acme, acme):
    response = client_as(admin_acme).post(
        ROLES_URL,
        {"org_id": acme.id, "name": "Auditor", "permissions": [_audit_entry()]},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert _entry(response.json(), "audit")["audit_history_days"] == 0
    assert _policy_days(response.json()["id"]) is None


@pytest.mark.django_db
def test_create_with_export_only_accepts_a_limit(client_as, admin_acme, acme):
    response = client_as(admin_acme).post(
        ROLES_URL,
        {"org_id": acme.id, "name": "Exporter", "permissions": [_audit_entry(7, ["export"])]},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert _policy_days(response.json()["id"]) == 7


INVALID_BODIES = {
    "limit on a non-audit entry": [
        {"resource_type": "flows", "actions": ["read"], "audit_history_days": 30}
    ],
    "non-zero limit without read or export": [_audit_entry(30, actions=[])],
    "negative": [_audit_entry(-1)],
    "above max": [_audit_entry(AUDIT_HISTORY_DAYS_MAX + 1)],
    "string": [_audit_entry("30")],
    "bool": [_audit_entry(True)],
    "null": [_audit_entry(None) | {"audit_history_days": None}],
    "float": [_audit_entry(1.5)],
}


@pytest.mark.django_db
@pytest.mark.parametrize("permissions", list(INVALID_BODIES.values()), ids=list(INVALID_BODIES))
def test_create_rejects_an_invalid_limit(client_as, admin_acme, acme, permissions):
    response = client_as(admin_acme).post(
        ROLES_URL,
        {"org_id": acme.id, "name": "Invalid", "permissions": permissions},
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Role.objects.filter(org=acme, name="Invalid").exists()


@pytest.mark.django_db
def test_create_rejects_the_old_top_level_limit(client_as, admin_acme, acme):
    response = client_as(admin_acme).post(
        ROLES_URL,
        {
            "org_id": acme.id,
            "name": "Old shape",
            "permissions": [_audit_entry()],
            "audit_history_days": 30,
        },
        format="json",
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert not Role.objects.filter(org=acme, name="Old shape").exists()


# ---- update ----


@pytest.mark.django_db
def test_patch_rejects_the_old_top_level_limit(client_as, admin_acme, acme):
    role = _audit_role(acme, "Untouched", history_days=5)

    response = client_as(admin_acme).patch(
        _detail_url(role), {"audit_history_days": 30}, format="json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert _policy_days(role.id) == 5


@pytest.mark.django_db
def test_patch_changes_an_existing_limit(client_as, admin_acme, acme):
    role = _audit_role(acme, "Reviewer", history_days=30)

    response = client_as(admin_acme).patch(
        _detail_url(role), {"permissions": [_audit_entry(7)]}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.json()
    assert _entry(response.json(), "audit")["audit_history_days"] == 7
    assert _policy_days(role.id) == 7


@pytest.mark.django_db
def test_patch_removing_every_audit_action_deletes_the_policy(client_as, admin_acme, acme):
    role = _audit_role(acme, "Former auditor", history_days=30)

    response = client_as(admin_acme).patch(
        _detail_url(role),
        {"permissions": [{"resource_type": "flows", "actions": ["read"]}]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.json()
    assert _policy_days(role.id) is None


@pytest.mark.django_db
def test_patch_without_permissions_leaves_the_limit_untouched(client_as, admin_acme, acme):
    role = _audit_role(acme, "Renamed later", history_days=30)

    response = client_as(admin_acme).patch(_detail_url(role), {"name": "Renamed"}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.json()
    assert _entry(response.json(), "audit")["audit_history_days"] == 30
    assert _policy_days(role.id) == 30


@pytest.mark.django_db
def test_patch_permissions_without_a_limit_makes_the_role_unlimited(client_as, admin_acme, acme):
    """`permissions` is a full replacement and the limit travels inside it."""
    role = _audit_role(acme, "Widened", history_days=30)

    response = client_as(admin_acme).patch(
        _detail_url(role), {"permissions": [_audit_entry()]}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.json()
    assert _entry(response.json(), "audit")["audit_history_days"] == 0
    assert _policy_days(role.id) is None


@pytest.mark.django_db
def test_patch_a_role_in_another_org_is_404(client_as, admin_acme, beta):
    role = _audit_role(beta, "Beta auditor", history_days=5)

    response = client_as(admin_acme).patch(
        _detail_url(role), {"permissions": [_audit_entry(1)]}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert _policy_days(role.id) == 5


@pytest.mark.django_db
def test_built_in_role_limit_cannot_be_edited(client_as, admin_acme, role_org_admin):
    response = client_as(admin_acme).patch(
        _detail_url(role_org_admin), {"permissions": [_audit_entry(30)]}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert _policy_days(role_org_admin.id) is None


# ---- the ceiling ----


@pytest.mark.django_db
@pytest.mark.parametrize("requested", [0, None, 90])
def test_limited_actor_cannot_widen_their_own_role(
    client_as, limited_role_manager, acme, requested
):
    """The exploit: a role manager limited to 30 days edits their own role to
    unlimited (or wider) and would then read the whole audit history."""
    own_role = OrganizationUser.objects.get(user=limited_role_manager, org=acme).role

    response = client_as(limited_role_manager).patch(
        _detail_url(own_role),
        {
            "permissions": [
                _audit_entry(requested),
                {"resource_type": "roles", "actions": ["create", "read", "update", "delete"]},
            ]
        },
        format="json",
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["code"] == "permission_escalation_denied"
    assert _policy_days(own_role.id) == 30


@pytest.mark.django_db
@pytest.mark.parametrize(("requested", "allowed"), [(90, False), (0, False), (30, True), (7, True)])
def test_limited_actor_creates_roles_within_their_own_limit(
    client_as, limited_role_manager, acme, requested, allowed
):
    response = client_as(limited_role_manager).post(
        ROLES_URL,
        {"org_id": acme.id, "name": "Delegated auditor", "permissions": [_audit_entry(requested)]},
        format="json",
    )

    if allowed:
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert _policy_days(response.json()["id"]) == requested
    else:
        assert response.status_code == status.HTTP_403_FORBIDDEN
        assert response.json()["code"] == "permission_escalation_denied"
        assert not Role.objects.filter(org=acme, name="Delegated auditor").exists()


@pytest.mark.django_db
def test_superadmin_grants_any_limit(client_as, superadmin, acme):
    response = client_as(superadmin).post(
        ROLES_URL,
        {"org_id": acme.id, "name": "Unlimited auditor", "permissions": [_audit_entry()]},
        format="json",
    )

    assert response.status_code == status.HTTP_201_CREATED, response.json()
    assert _policy_days(response.json()["id"]) is None


# ---- read ----


@pytest.mark.django_db
def test_detail_list_and_built_ins_show_the_limit_on_the_audit_entry(client_as, admin_acme, acme):
    role = _audit_role(acme, "Reader", history_days=7)
    client = client_as(admin_acme)

    detail = client.get(_detail_url(role)).json()
    listed = client.get(ROLES_URL, {"org_ids": acme.id}).json()

    assert _entry(detail, "audit")["audit_history_days"] == 7
    listed_role = next(row for row in listed["results"] if row["id"] == role.id)
    assert _entry(listed_role, "audit")["audit_history_days"] == 7
    org_admin = next(row for row in listed["built_in_roles"] if row["name"] == BuiltInRole.ORG_ADMIN)
    assert _entry(org_admin, "audit")["audit_history_days"] == 0
    assert all("audit_history_days" not in row for row in listed["built_in_roles"])


@pytest.mark.django_db
def test_roles_list_does_not_query_the_policy_per_role(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    _audit_role(acme, "Policy one", history_days=1)

    def count_list_queries():
        with CaptureQueriesContext(connection) as queries:
            assert client.get(ROLES_URL, {"org_ids": acme.id}).status_code == status.HTTP_200_OK
        return len(queries)

    baseline = count_list_queries()
    for index in range(2, 5):
        _audit_role(acme, f"Policy {index}", history_days=index)
    _audit_role(acme, "No policy")

    assert count_list_queries() == baseline
