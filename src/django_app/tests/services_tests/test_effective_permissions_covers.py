"""The escalation ceiling as a pure comparison.

`EffectivePermissions.covers` is the single implementation of "is every
requested bit within mine", shared by role authoring (the bits being written
into a role) and role assignment (the bits the assigned role grants). These
tests pin the comparison itself; the two call paths are tested where they live.
"""

import pytest

from rbac.models import Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from rbac.access.effective import EffectivePermissions

ROLES = ResourceType.ROLES.value
FLOWS = ResourceType.FLOWS.value
AGENTS = ResourceType.AGENTS.value


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
# Grantability is per-resource: `use` is an action of `secrets` and `flows`
# only, `list` of nothing at all. The database can nonetheless hold bits that
# are not actions of their own resource -- rows seeded or written before the
# catalog settled. Comparing those lets dead data refuse a legitimate grant,
# which is exactly what once broke Org Admin -> Viewer (`flows: 66` carried
# USE before `use` became an action of `flows`).


def test_ungrantable_bits_in_the_request_are_ignored():
    """A stale `agents: 66` row is READ|USE. Org Admin's `agents: 31` is
    CRUD+Export and carries no USE bit, so a raw comparison refuses the
    assignment. `use` is not an action of `agents`, so it must not be compared
    there even though it is an action of `secrets` and `flows`."""
    org_admin = _effective({AGENTS: 31})

    assert org_admin.covers({AGENTS: int(Permission.READ | Permission.USE)})


def test_ungrantable_bits_do_not_widen_the_ceiling():
    """The mask must not let USE/LIST stand in for a grantable bit the caller
    does not hold: holding only bits that are not actions of the resource
    grants nothing assignable."""
    ungrantable_only = _effective({AGENTS: int(Permission.USE | Permission.LIST)})

    assert not ungrantable_only.covers({AGENTS: int(Permission.READ)})


def test_grantable_bits_are_still_compared_exactly():
    """Masking drops only what is ungrantable on that resource -- every action
    the resource does declare still counts."""
    caller = _effective({AGENTS: int(Permission.READ | Permission.USE)})

    assert caller.covers({AGENTS: int(Permission.READ)})
    assert not caller.covers({AGENTS: int(Permission.READ | Permission.EXPORT)})


def test_flows_use_is_compared_like_any_grantable_bit():
    """`use` is an action of `flows`, so a caller without it cannot hand it out,
    and Org Admin's old `flows: 31` no longer covers a role holding it."""
    reader = _effective({FLOWS: int(Permission.READ)})
    flows_user = _effective({FLOWS: int(Permission.READ | Permission.USE)})

    assert not reader.covers({FLOWS: int(Permission.READ | Permission.USE)})
    assert not _effective({FLOWS: 31}).covers({FLOWS: int(Permission.READ | Permission.USE)})
    assert flows_user.covers({FLOWS: int(Permission.READ | Permission.USE)})
