import pytest
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
    RolePermission,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType
from tables.services.rbac.rbac_exceptions import (
    BuiltInRoleImmutableError,
    PermissionEscalationError,
    RoleNameConflictError,
    RoleNotFoundError,
)
from tables.services.rbac.role_management_service import RoleManagementService


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
        permissions=[_perm("secrets", int(Permission.READ | Permission.UPDATE))],
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

    with pytest.raises(PermissionEscalationError):
        service.create_role(
            actor=manager,
            org_id=org.id,
            name="TooPowerful",
            description=None,
            permissions=[_perm("secrets", int(Permission.READ | Permission.UPDATE))],
        )


@pytest.mark.django_db
def test_create_role_superadmin_bypasses_ceiling(service, superadmin, org):
    role = service.create_role(
        actor=superadmin,
        org_id=org.id,
        name="Anything",
        description=None,
        permissions=[_perm("secrets", int(Permission.CREATE | Permission.DELETE))],
    )
    assert role.pk is not None


@pytest.mark.django_db
def test_create_role_duplicate_name_conflict(service, org_admin, org):
    service.create_role(
        actor=org_admin, org_id=org.id, name="Dup", description=None, permissions=[]
    )
    with pytest.raises(RoleNameConflictError):
        service.create_role(
            actor=org_admin, org_id=org.id, name="dup", description=None, permissions=[]
        )


@pytest.mark.django_db
def test_update_builtin_rejected(service, org_admin, role_member):
    with pytest.raises(BuiltInRoleImmutableError):
        service.update_role(
            actor=org_admin, role_id=role_member.id, changes={"name": "X"}
        )


@pytest.mark.django_db
def test_delete_reassigns_members_to_member(
    service, org_admin, org, role_member, django_user_model
):
    custom = service.create_role(
        actor=org_admin, org_id=org.id, name="Temp", description=None, permissions=[]
    )
    victim = django_user_model.objects.create_user(
        email="victim-write@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=victim, org=org, role=custom)

    count = service.delete_role(actor=org_admin, role_id=custom.id)

    assert count == 1
    assert not Role.objects.filter(pk=custom.id).exists()
    membership = OrganizationUser.objects.get(user=victim, org=org)
    assert membership.role_id == role_member.id  # reassigned, not evicted


@pytest.mark.django_db
def test_preview_delete_lists_affected_without_mutating(
    service, org_admin, org, django_user_model
):
    custom = service.create_role(
        actor=org_admin, org_id=org.id, name="Temp2", description=None, permissions=[]
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
        permissions=[_perm("secrets", int(Permission.READ))],
    )
    updated = service.update_role(
        actor=org_admin,
        role_id=role.id,
        changes={
            "name": "Renamed",
            "description": "new",
            "permissions": [_perm("secrets", int(Permission.READ | Permission.UPDATE))],
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
        permissions=[_perm("secrets", int(Permission.READ))],
    )
    with pytest.raises(PermissionEscalationError):
        service.update_role(
            actor=manager,
            role_id=target.id,
            changes={
                "permissions": [
                    _perm("secrets", int(Permission.READ | Permission.UPDATE))
                ]
            },
        )


@pytest.mark.django_db
def test_update_role_rename_to_existing_name_conflicts(service, org_admin, org):
    service.create_role(
        actor=org_admin, org_id=org.id, name="Alpha", description=None, permissions=[]
    )
    beta = service.create_role(
        actor=org_admin, org_id=org.id, name="Beta", description=None, permissions=[]
    )
    with pytest.raises(RoleNameConflictError):
        service.update_role(actor=org_admin, role_id=beta.id, changes={"name": "alpha"})
