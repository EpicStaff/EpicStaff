import pytest
from rest_framework.exceptions import PermissionDenied

from rbac.models import Organization, OrganizationUser, Role, RoleAuditPolicy, RolePermission
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from rbac.exceptions import (
    BuiltInRoleImmutableError,
    OrganizationNotFoundError,
    PermissionEscalationError,
    RoleNameConflictError,
    RoleNotFoundError,
)
from rbac.governance.roles import RoleManagementService


@pytest.fixture
def service():
    return RoleManagementService()


@pytest.fixture
def role_org_admin(db):
    return Role.objects.get(
        name=BuiltInRole.ORG_ADMIN, is_built_in=True, org__isnull=True
    )


@pytest.fixture
def role_member(db):
    return Role.objects.get(name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True)


@pytest.fixture
def role_viewer(db):
    return Role.objects.get(name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True)


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Acme-write")


@pytest.fixture
def superadmin(db, django_user_model):
    return django_user_model.objects.create_superuser(
        email="su-write@example.com", password="StrongPass123!"
    )


@pytest.fixture
def org_admin(db, django_user_model, org, role_org_admin):
    user = django_user_model.objects.create_user(
        email="admin-write@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role_org_admin)
    return user


def _perm(resource, bitmask):
    return {"resource_type": resource, "bitmask": bitmask}


@pytest.mark.django_db
def test_create_role_by_org_admin(service, org_admin, org):
    role = service.create_role(
        actor=org_admin,
        org_id=org.id,
        name="Billing Manager",
        description="d",
        permissions=[_perm("secrets", int(Permission.READ | Permission.UPDATE))], audit_history_days=0,
    )
    assert role.org_id == org.id
    assert role.is_built_in is False
    row = RolePermission.objects.get(role=role, resource_type="secrets")
    assert row.permissions == int(Permission.READ | Permission.UPDATE)


@pytest.mark.django_db
def test_create_role_ceiling_blocks_escalation(service, django_user_model, org):
    # A role-manager who has ROLES CRUD but only secrets READ.
    manager_role = Role.objects.create(name="RoleMgr", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=manager_role,
        resource_type="roles",
        permissions=int(
            Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
        ),
    )
    RolePermission.objects.create(
        role=manager_role, resource_type="secrets", permissions=int(Permission.READ)
    )
    manager = django_user_model.objects.create_user(
        email="mgr-write@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=manager, org=org, role=manager_role)

    # DELETE, not UPDATE: the ceiling compares only actions the catalog can
    # actually grant on that resource, and `secrets` has no `update` action
    # (a Secret is immutable, so SecretViewSet exposes no update route).
    # Escalating on an ungrantable bit would prove nothing -- the validator
    # rejects it long before the ceiling runs.
    with pytest.raises(PermissionEscalationError):
        service.create_role(
            actor=manager,
            org_id=org.id,
            name="TooPowerful",
            description=None,
            permissions=[_perm("secrets", int(Permission.READ | Permission.DELETE))], audit_history_days=0,
        )


@pytest.mark.django_db
def test_create_role_superadmin_bypasses_ceiling(service, superadmin, org):
    role = service.create_role(
        actor=superadmin,
        org_id=org.id,
        name="Anything",
        description=None,
        permissions=[_perm("secrets", int(Permission.CREATE | Permission.DELETE))], audit_history_days=0,
    )
    assert role.pk is not None


@pytest.mark.django_db
def test_create_role_superadmin_nonexistent_org_is_404(service, superadmin):
    # Superadmin bypasses the membership check, so a bad org_id must be turned
    # into a 404 rather than an FK IntegrityError (500).
    with pytest.raises(OrganizationNotFoundError):
        service.create_role(
            actor=superadmin,
            org_id=999999,
            name="Ghost",
            description=None,
            permissions=[], audit_history_days=0,
        )


@pytest.mark.django_db
def test_create_role_duplicate_name_conflict(service, org_admin, org):
    service.create_role(
        actor=org_admin, org_id=org.id, name="Dup", description=None, permissions=[], audit_history_days=0
    )
    with pytest.raises(RoleNameConflictError):
        service.create_role(
            actor=org_admin, org_id=org.id, name="dup", description=None, permissions=[], audit_history_days=0
        )


@pytest.mark.django_db
def test_update_builtin_rejected(service, org_admin, role_member):
    with pytest.raises(BuiltInRoleImmutableError):
        service.update_role(
            actor=org_admin, role_id=role_member.id, changes={"name": "X"}
        )


@pytest.mark.django_db
def test_delete_reassigns_members_to_viewer(
    service, org_admin, org, role_viewer, django_user_model
):
    custom = service.create_role(
        actor=org_admin, org_id=org.id, name="Temp", description=None, permissions=[], audit_history_days=0
    )
    victim = django_user_model.objects.create_user(
        email="victim-write@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=victim, org=org, role=custom)

    count = service.delete_role(actor=org_admin, role_id=custom.id)

    assert count == 1
    assert not Role.objects.filter(pk=custom.id).exists()
    membership = OrganizationUser.objects.get(user=victim, org=org)
    assert membership.role_id == role_viewer.id  # reassigned to Viewer, not evicted


@pytest.mark.django_db
def test_update_role_cross_org_is_404(service, django_user_model, org, role_member):
    other_org = Organization.objects.create(name="Other-write-upd")
    stranger = django_user_model.objects.create_user(
        email="stranger-upd@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=stranger, org=other_org, role=role_member)
    secret_role = Role.objects.create(name="SecretUpd", org=org, is_built_in=False)
    with pytest.raises(RoleNotFoundError):
        service.update_role(
            actor=stranger, role_id=secret_role.id, changes={"name": "X"}
        )


@pytest.mark.django_db
def test_delete_role_cross_org_is_404(service, django_user_model, org, role_member):
    other_org = Organization.objects.create(name="Other-write-del")
    stranger = django_user_model.objects.create_user(
        email="stranger-del@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=stranger, org=other_org, role=role_member)
    secret_role = Role.objects.create(name="SecretDel", org=org, is_built_in=False)
    with pytest.raises(RoleNotFoundError):
        service.delete_role(actor=stranger, role_id=secret_role.id)


@pytest.mark.django_db
def test_preview_delete_lists_affected_without_mutating(
    service, org_admin, org, django_user_model
):
    custom = service.create_role(
        actor=org_admin, org_id=org.id, name="Temp2", description=None, permissions=[], audit_history_days=0
    )
    victim = django_user_model.objects.create_user(
        email="victim2-write@example.com", password="StrongPass123!", display_name="Vic"
    )
    OrganizationUser.objects.create(user=victim, org=org, role=custom)

    preview = service.preview_delete(actor=org_admin, role_id=custom.id)

    assert preview["assigned_count"] == 1
    assert preview["affected_users"][0]["email"] == "victim2-write@example.com"
    assert Role.objects.filter(pk=custom.id).exists()  # not deleted


@pytest.mark.django_db
def test_preview_delete_uses_same_auth_as_delete_no_read_required(
    service, django_user_model, org
):
    # A role holding ROLES.DELETE but NOT ROLES.READ can delete a role; the
    # preview must accept the same caller instead of demanding READ (else the
    # safe dry-run 404s while the destructive delete succeeds).
    deleter_role = Role.objects.create(name="Deleter", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=deleter_role, resource_type="roles", permissions=int(Permission.DELETE)
    )
    deleter = django_user_model.objects.create_user(
        email="deleter-write@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=deleter, org=org, role=deleter_role)
    target = Role.objects.create(name="TargetDel", org=org, is_built_in=False)

    preview = service.preview_delete(actor=deleter, role_id=target.id)

    assert preview["role_id"] == target.id
    assert preview["assigned_count"] == 0
    assert Role.objects.filter(pk=target.id).exists()  # preview did not mutate


@pytest.mark.django_db
def test_preview_delete_cross_org_is_404(service, django_user_model, org, role_member):
    other_org = Organization.objects.create(name="Other-preview-del")
    stranger = django_user_model.objects.create_user(
        email="stranger-preview@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=stranger, org=other_org, role=role_member)
    secret_role = Role.objects.create(name="SecretPreview", org=org, is_built_in=False)
    with pytest.raises(RoleNotFoundError):
        service.preview_delete(actor=stranger, role_id=secret_role.id)


@pytest.mark.django_db
def test_get_role_for_read_cross_org_is_404(
    service, django_user_model, org, role_member
):
    other_org = Organization.objects.create(name="Other-write")
    stranger = django_user_model.objects.create_user(
        email="stranger-write@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=stranger, org=other_org, role=role_member)
    secret_role = Role.objects.create(name="Secret", org=org, is_built_in=False)

    with pytest.raises(RoleNotFoundError):
        service.get_role_for_read(actor=stranger, role_id=secret_role.id)


@pytest.mark.django_db
def test_list_custom_roles_forbidden_org_raises(service, org_admin, org):
    other = Organization.objects.create(name="Forbidden-write")
    with pytest.raises(PermissionDenied):
        service.list_custom_roles(actor=org_admin, org_ids=[other.id])


@pytest.mark.django_db
def test_update_role_replaces_name_desc_and_permissions(service, org_admin, org):
    role = service.create_role(
        actor=org_admin,
        org_id=org.id,
        name="Editable",
        description="old",
        permissions=[_perm("secrets", int(Permission.READ))], audit_history_days=0,
    )
    updated = service.update_role(
        actor=org_admin,
        role_id=role.id,
        changes={
            "name": "Renamed",
            "description": "new",
            "permissions": [_perm("secrets", int(Permission.READ | Permission.UPDATE))],
            "audit_history_days": 0,
        },
    )
    assert updated.name == "Renamed"
    assert updated.description == "new"
    row = RolePermission.objects.get(role=role, resource_type="secrets")
    assert row.permissions == int(Permission.READ | Permission.UPDATE)


@pytest.mark.django_db
def test_update_role_ceiling_blocks_added_bit(service, django_user_model, org):
    manager_role = Role.objects.create(name="RoleMgrUpd", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=manager_role,
        resource_type="roles",
        permissions=int(
            Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
        ),
    )
    RolePermission.objects.create(
        role=manager_role, resource_type="secrets", permissions=int(Permission.READ)
    )
    manager = django_user_model.objects.create_user(
        email="mgr-upd@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=manager, org=org, role=manager_role)
    target = service.create_role(
        actor=manager,
        org_id=org.id,
        name="TargetUpd",
        description=None,
        permissions=[_perm("secrets", int(Permission.READ))], audit_history_days=0,
    )
    # DELETE rather than UPDATE, for the reason given in
    # test_create_role_ceiling_blocks_escalation.
    with pytest.raises(PermissionEscalationError):
        service.update_role(
            actor=manager,
            role_id=target.id,
            changes={
                "permissions": [
                    _perm("secrets", int(Permission.READ | Permission.DELETE))
                ],
                "audit_history_days": 0,
            },
        )


@pytest.mark.django_db
def test_update_role_rename_to_existing_name_conflicts(service, org_admin, org):
    service.create_role(
        actor=org_admin, org_id=org.id, name="Alpha", description=None, permissions=[], audit_history_days=0
    )
    beta = service.create_role(
        actor=org_admin, org_id=org.id, name="Beta", description=None, permissions=[], audit_history_days=0
    )
    with pytest.raises(RoleNameConflictError):
        service.update_role(actor=org_admin, role_id=beta.id, changes={"name": "alpha"})


# ---- the audit history limit under the escalation ceiling ----
#
# Unlimited (0) is the widest limit. An actor limited to N days may hand out 1..N on
# a role that reads audit, never unlimited and never more than N.

AUDIT_READ = int(Permission.READ)
ROLES_CRUD = int(Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE)


def _policy_days(role):
    policy = RoleAuditPolicy.objects.filter(role=role).first()
    return None if policy is None else policy.history_days


def _audit_role(org, name, history_days):
    role = Role.objects.create(name=name, org=org, is_built_in=False)
    RolePermission.objects.create(role=role, resource_type="audit", permissions=AUDIT_READ)
    if history_days:
        RoleAuditPolicy.objects.create(role=role, history_days=history_days)
    return role


@pytest.fixture
def limited_manager(db, django_user_model, org):
    """Manages roles and reads audit in `org`, limited to 30 days."""
    role = _audit_role(org, "Limited manager", history_days=30)
    RolePermission.objects.create(role=role, resource_type="roles", permissions=ROLES_CRUD)
    user = django_user_model.objects.create_user(
        email="limited-manager@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    return user


@pytest.mark.django_db
@pytest.mark.parametrize("requested", [0, 31])
def test_update_own_role_to_a_wider_limit_is_refused(service, limited_manager, org, requested):
    own_role = OrganizationUser.objects.get(user=limited_manager, org=org).role

    with pytest.raises(PermissionEscalationError):
        service.update_role(
            actor=limited_manager,
            role_id=own_role.id,
            changes={
                "permissions": [_perm("audit", AUDIT_READ), _perm("roles", ROLES_CRUD)],
                "audit_history_days": requested,
            },
        )

    assert _policy_days(own_role) == 30


@pytest.mark.django_db
@pytest.mark.parametrize("requested", [0, 90])
def test_create_role_with_a_wider_limit_is_refused(service, limited_manager, org, requested):
    with pytest.raises(PermissionEscalationError):
        service.create_role(
            actor=limited_manager,
            org_id=org.id,
            name="Too wide",
            description=None,
            permissions=[_perm("audit", AUDIT_READ)],
            audit_history_days=requested,
        )

    assert not Role.objects.filter(org=org, name="Too wide").exists()


@pytest.mark.django_db
def test_create_role_within_the_limit_stores_it(service, limited_manager, org):
    role = service.create_role(
        actor=limited_manager,
        org_id=org.id,
        name="Narrow",
        description=None,
        permissions=[_perm("audit", AUDIT_READ)],
        audit_history_days=7,
    )

    assert _policy_days(role) == 7


@pytest.mark.django_db
def test_limit_on_a_role_without_audit_actions_is_not_stored(service, org_admin, org):
    """The service never keeps a policy row for a role that cannot read audit,
    even if a caller skips the validator."""
    role = service.create_role(
        actor=org_admin,
        org_id=org.id,
        name="No audit",
        description=None,
        permissions=[_perm("flows", AUDIT_READ)],
        audit_history_days=30,
    )

    assert _policy_days(role) is None


@pytest.mark.django_db
def test_superadmin_bypasses_the_limit_ceiling(service, superadmin, org, limited_manager):
    own_role = OrganizationUser.objects.get(user=limited_manager, org=org).role

    service.update_role(
        actor=superadmin,
        role_id=own_role.id,
        changes={
            "permissions": [_perm("audit", AUDIT_READ), _perm("roles", ROLES_CRUD)],
            "audit_history_days": 0,
        },
    )

    assert _policy_days(own_role) is None


@pytest.mark.django_db
def test_assignable_picker_hides_roles_with_a_wider_limit(service, limited_manager, org):
    narrower = _audit_role(org, "Seven days", history_days=7)
    wider = _audit_role(org, "Ninety days", history_days=90)
    unlimited = _audit_role(org, "Unlimited", history_days=None)

    assignable_in = service.resolve_assignable_scopes(actor=limited_manager, org_ids=[org.id])
    custom = service.list_custom_roles(
        actor=limited_manager, org_ids=[org.id], assignable_in=assignable_in
    )

    names = {role.name for role in custom}
    assert narrower.name in names
    assert wider.name not in names
    assert unlimited.name not in names
