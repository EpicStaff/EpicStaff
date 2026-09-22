"""The escalation ceiling as a pure comparison.

`EffectivePermissions.covers` is the single implementation of "is every
requested bit within mine", shared by role authoring (the bits being written
into a role) and role assignment (the bits the assigned role grants). These
tests pin the comparison itself; the two call paths are tested where they live.
"""

import pytest

from rbac.models import Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.services.rbac.effective_permissions import EffectivePermissions

ROLES = ResourceType.ROLES.value
FLOWS = ResourceType.FLOWS.value


def _effective(by_resource):
    return EffectivePermissions(is_superadmin=False, role=None, by_resource=by_resource)


def test_proper_subset_is_covered():
    caller = _effective({ROLES: int(Permission.READ | Permission.UPDATE)})

    assert caller.covers({ROLES: int(Permission.READ)})


def test_equal_masks_are_covered():
    mask = int(Permission.READ | Permission.UPDATE)

    assert _effective({ROLES: mask}).covers({ROLES: mask})


def test_one_extra_bit_is_not_covered():
    caller = _effective({ROLES: int(Permission.READ)})

    assert not caller.covers({ROLES: int(Permission.READ | Permission.DELETE)})


def test_resource_the_caller_holds_nothing_on_is_not_covered():
    """A resource absent from the caller's map counts as zero, so any
    non-zero request on it escalates."""
    caller = _effective({ROLES: int(Permission.READ)})

    assert not caller.covers({FLOWS: int(Permission.READ)})


def test_zero_request_on_an_unheld_resource_is_covered():
    """Zero grants nothing, so it is never an escalation -- this is what lets
    a role carrying an all-zero row be assigned."""
    assert _effective({ROLES: int(Permission.READ)}).covers({FLOWS: 0})


def test_empty_request_is_covered():
    assert _effective({}).covers({})


def test_a_single_over_ceiling_resource_fails_the_whole_comparison():
    """Every resource must pass; one violation is enough to refuse."""
    caller = _effective({ROLES: int(Permission.READ), FLOWS: int(Permission.READ)})

    assert not caller.covers(
        {ROLES: int(Permission.READ), FLOWS: int(Permission.READ | Permission.CREATE)}
    )


def test_superadmin_covers_everything():
    superadmin = EffectivePermissions(is_superadmin=True, role=None, by_resource={})

    assert superadmin.covers({ROLES: 15, FLOWS: 31})


@pytest.mark.django_db
def test_bits_of_reads_a_roles_permission_rows(db):
    role = Role.objects.create(name="Bits-of-probe", is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ROLES, permissions=int(Permission.READ)
    )
    RolePermission.objects.create(
        role=role, resource_type=FLOWS, permissions=int(Permission.CREATE)
    )

    assert EffectivePermissions.bits_of(role) == {
        ROLES: int(Permission.READ),
        FLOWS: int(Permission.CREATE),
    }


@pytest.mark.django_db
def test_from_role_and_bits_of_agree(db):
    """`from_role` must read a role's bits the same way `bits_of` does --
    one implementation, so the ceiling and the resolver cannot disagree."""
    role = Role.objects.create(name="Agree-probe", is_built_in=False)
    RolePermission.objects.create(
        role=role, resource_type=ROLES, permissions=int(Permission.UPDATE)
    )

    assert EffectivePermissions.from_role(role).by_resource == (
        EffectivePermissions.bits_of(role)
    )


# ---- ungrantable bits are excluded from the comparison ----
#
# Grantability is per-resource: `use` is an action of `secrets` and of nothing
# else, `list` of nothing at all. The database nonetheless holds bits that are
# not actions of their own resource (Viewer `flows: 66` carries USE), seeded
# before the catalog settled. Comparing those lets dead data refuse a
# legitimate grant, which is exactly what broke Org Admin -> Viewer once `use`
# was enabled for secrets.


def test_ungrantable_bits_in_the_request_are_ignored():
    """Viewer's `flows: 66` is READ|USE. Org Admin's `flows: 31` is CRUD+Export
    and carries no USE bit, so a raw comparison refuses the assignment -- the
    most ordinary delegated operation there is. `use` is not an action of
    `flows`, so it must not be compared there even though it is an action of
    `secrets`."""
    org_admin = _effective({FLOWS: 31})

    assert org_admin.covers({FLOWS: 66})


def test_ungrantable_bits_do_not_widen_the_ceiling():
    """The mask must not let USE/LIST stand in for a grantable bit the caller
    does not hold: holding only USE grants nothing assignable."""
    use_only = _effective({FLOWS: int(Permission.USE)})

    assert not use_only.covers({FLOWS: int(Permission.READ)})


def test_grantable_bits_are_still_compared_exactly():
    """Masking drops only what is ungrantable on that resource -- every action
    the resource does declare still counts."""
    caller = _effective({FLOWS: int(Permission.READ | Permission.USE)})

    assert caller.covers({FLOWS: int(Permission.READ)})
    assert not caller.covers({FLOWS: int(Permission.READ | Permission.EXPORT)})
