"""Invariants the built-in role seeds must satisfy.

Migration 0242 re-seeded the three built-in roles so that every stored bit is
one the code enforces *and* the catalog can grant. These tests pin that state,
because a bit which grants nothing is not harmless: the escalation ceiling
compares these masks when deciding whether the holder of one role may assign
another, so dead data can refuse a legitimate assignment. That is exactly how
`flows: USE` on Viewer -- seeded in 0171 as "can run flows", enforced nowhere,
dormant until `use` became a catalog action for `secrets` -- came to block
every Org Admin from assigning Viewer.
"""

import pytest

from rbac.models import Role, RolePermission
from rbac.models.enums import BuiltInRole, Permission, ResourceType
from tables.services.rbac.effective_permissions import EffectivePermissions
from tables.services.rbac.permission_catalog import grantable_bits_for

DELEGATED = [BuiltInRole.ORG_ADMIN, BuiltInRole.MEMBER, BuiltInRole.VIEWER]


def _builtin(name):
    return Role.objects.get(name=name, is_built_in=True, org__isnull=True)


@pytest.mark.django_db
@pytest.mark.parametrize("role_name", DELEGATED)
def test_every_stored_bit_is_grantable_on_its_resource(role_name):
    """No built-in may hold a bit that is not an action of its own resource.

    Guards against a future seed reintroducing one: an ungrantable bit cannot
    be reached through the permission matrix, is enforced nowhere, and only
    ever distorts the ceiling comparison.
    """
    role = _builtin(role_name)

    stray = {
        row.resource_type: row.permissions & ~grantable_bits_for(row.resource_type)
        for row in RolePermission.objects.filter(role=role)
        if row.permissions & ~grantable_bits_for(row.resource_type)
    }

    assert stray == {}, f"{role_name} holds ungrantable bits: {stray}"


@pytest.mark.django_db
def test_superadmin_role_holds_no_permission_rows():
    """Superadmin authority is the `User.is_superadmin` flag, never a bitmask."""
    role = _builtin(BuiltInRole.SUPERADMIN)

    assert not RolePermission.objects.filter(role=role).exclude(permissions=0).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("target_name", [BuiltInRole.MEMBER, BuiltInRole.VIEWER])
def test_org_admin_can_assign_the_lesser_built_ins(target_name):
    """The property the bug broke: an Org Admin must be able to hand out every
    role weaker than their own."""
    org_admin = EffectivePermissions.from_role(_builtin(BuiltInRole.ORG_ADMIN))

    assert org_admin.covers(EffectivePermissions.bits_of(_builtin(target_name)))


@pytest.mark.django_db
def test_secrets_use_is_held_by_org_admin_only():
    """`use` is an action of `secrets` alone, and among the built-ins only the
    Org Admin is trusted with it."""
    holders = {
        name
        for name in DELEGATED
        if EffectivePermissions.from_role(_builtin(name)).can(
            ResourceType.SECRETS.value, Permission.USE
        )
    }

    assert holders == {BuiltInRole.ORG_ADMIN}


@pytest.mark.django_db
@pytest.mark.parametrize("role_name", DELEGATED)
def test_no_built_in_holds_use_outside_secrets(role_name):
    """`use` is enforced only by SecretReferenceGuard, so it means nothing on
    any other resource."""
    role = _builtin(role_name)

    elsewhere = [
        row.resource_type
        for row in RolePermission.objects.filter(role=role).exclude(
            resource_type=ResourceType.SECRETS.value
        )
        if row.permissions & int(Permission.USE)
    ]

    assert elsewhere == []


@pytest.mark.django_db
@pytest.mark.parametrize("role_name", DELEGATED)
def test_no_built_in_holds_the_list_bit(role_name):
    """`Permission.LIST` is checked nowhere and is absent from the catalog."""
    role = _builtin(role_name)

    holding = [
        row.resource_type
        for row in RolePermission.objects.filter(role=role)
        if row.permissions & int(Permission.LIST)
    ]

    assert holding == []


@pytest.mark.django_db
def test_viewer_can_still_read_flows():
    """Removing the dead `flows: USE` bit must not cost Viewer the READ that
    running a flow actually requires (views.py RunSession)."""
    viewer = EffectivePermissions.from_role(_builtin(BuiltInRole.VIEWER))

    assert viewer.can(ResourceType.FLOWS.value, Permission.READ)
