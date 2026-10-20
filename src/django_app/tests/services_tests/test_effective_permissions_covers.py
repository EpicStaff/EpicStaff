"""The escalation ceiling as a pure comparison.

`EffectivePermissions.covers` is the single implementation of "is everything
requested within mine" -- every bit, and the audit history limit -- shared by
role authoring (what is written into a role) and role assignment (what the
assigned role grants). These
tests pin the comparison itself; the two call paths are tested where they live.
"""

import pytest

from rbac.models import Role, RoleAuditPolicy, RolePermission
from rbac.models.enums import Permission, ResourceType
from rbac.access.effective import EffectivePermissions, RoleGrant

ROLES = ResourceType.ROLES.value
FLOWS = ResourceType.FLOWS.value


def _effective(by_resource):
    return EffectivePermissions(is_superadmin=False, role=None, by_resource=by_resource)


def test_proper_subset_is_covered():
    caller = _effective({ROLES: int(Permission.READ | Permission.UPDATE)})

    assert caller.covers(RoleGrant({ROLES: int(Permission.READ)}))


def test_equal_masks_are_covered():
    mask = int(Permission.READ | Permission.UPDATE)

    assert _effective({ROLES: mask}).covers(RoleGrant({ROLES: mask}))


def test_one_extra_bit_is_not_covered():
    caller = _effective({ROLES: int(Permission.READ)})

    assert not caller.covers(RoleGrant({ROLES: int(Permission.READ | Permission.DELETE)}))


def test_resource_the_caller_holds_nothing_on_is_not_covered():
    """A resource absent from the caller's map counts as zero, so any
    non-zero request on it escalates."""
    caller = _effective({ROLES: int(Permission.READ)})

    assert not caller.covers(RoleGrant({FLOWS: int(Permission.READ)}))


def test_zero_request_on_an_unheld_resource_is_covered():
    """Zero grants nothing, so it is never an escalation -- this is what lets
    a role carrying an all-zero row be assigned."""
    assert _effective({ROLES: int(Permission.READ)}).covers(RoleGrant({FLOWS: 0}))


def test_empty_request_is_covered():
    assert _effective({}).covers(RoleGrant({}))


def test_a_single_over_ceiling_resource_fails_the_whole_comparison():
    """Every resource must pass; one violation is enough to refuse."""
    caller = _effective({ROLES: int(Permission.READ), FLOWS: int(Permission.READ)})

    assert not caller.covers(
        RoleGrant({ROLES: int(Permission.READ), FLOWS: int(Permission.READ | Permission.CREATE)})
    )


def test_superadmin_covers_everything():
    superadmin = EffectivePermissions(is_superadmin=True, role=None, by_resource={})

    assert superadmin.covers(RoleGrant({ROLES: 15, FLOWS: 31}))


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

    assert org_admin.covers(RoleGrant({FLOWS: 66}))


def test_ungrantable_bits_do_not_widen_the_ceiling():
    """The mask must not let USE/LIST stand in for a grantable bit the caller
    does not hold: holding only USE grants nothing assignable."""
    use_only = _effective({FLOWS: int(Permission.USE)})

    assert not use_only.covers(RoleGrant({FLOWS: int(Permission.READ)}))


def test_grantable_bits_are_still_compared_exactly():
    """Masking drops only what is ungrantable on that resource -- every action
    the resource does declare still counts."""
    caller = _effective({FLOWS: int(Permission.READ | Permission.USE)})

    assert caller.covers(RoleGrant({FLOWS: int(Permission.READ)}))
    assert not caller.covers(RoleGrant({FLOWS: int(Permission.READ | Permission.EXPORT)}))


# ---- the audit history limit is part of the ceiling ----
#
# 0 = unlimited, the widest value. An actor limited to N days may grant 1..N on a
# role that reads or exports audit, never unlimited and never more than N. A grant
# without an audit action is decided by the bits alone.

AUDIT = ResourceType.AUDIT.value
AUDIT_READ = int(Permission.READ)


def _auditor(history_days):
    return EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={AUDIT: int(Permission.READ | Permission.EXPORT)},
        audit_history_days=history_days,
    )


@pytest.mark.parametrize(
    ("actor_days", "granted_days", "covered"),
    [
        (0, 0, True),
        (0, 30, True),
        (30, 30, True),
        (30, 7, True),
        (30, 90, False),
        (30, 0, False),
    ],
)
def test_audit_history_limit_is_capped_at_the_actors_own(actor_days, granted_days, covered):
    grant = RoleGrant({AUDIT: AUDIT_READ}, audit_history_days=granted_days)

    assert _auditor(actor_days).covers(grant) is covered


def test_export_alone_also_brings_the_limit_under_the_ceiling():
    grant = RoleGrant({AUDIT: int(Permission.EXPORT)}, audit_history_days=0)

    assert not _auditor(30).covers(grant)


def test_limit_is_not_compared_when_the_grant_has_no_audit_action():
    """A limited actor may still hand out a role that cannot read audit at all;
    whatever limit value travels with it means nothing."""
    grant = RoleGrant({AUDIT: 0}, audit_history_days=0)

    assert _auditor(30).covers(grant)


def test_actor_without_audit_read_is_refused_by_the_bits_first():
    caller = EffectivePermissions(
        is_superadmin=False, role=None, by_resource={ROLES: AUDIT_READ}, audit_history_days=0
    )

    assert not caller.covers(RoleGrant({AUDIT: AUDIT_READ}, audit_history_days=0))


def test_superadmin_covers_any_audit_limit():
    superadmin = EffectivePermissions(is_superadmin=True, role=None, by_resource={})

    assert superadmin.covers(RoleGrant({AUDIT: AUDIT_READ}, audit_history_days=0))


@pytest.mark.django_db
def test_from_role_and_of_role_read_the_audit_policy(db):
    limited = Role.objects.create(name="Limited-probe", is_built_in=False)
    RolePermission.objects.create(role=limited, resource_type=AUDIT, permissions=AUDIT_READ)
    RoleAuditPolicy.objects.create(role=limited, history_days=30)
    unlimited = Role.objects.create(name="Unlimited-probe", is_built_in=False)

    assert EffectivePermissions.from_role(limited).audit_history_days == 30
    assert RoleGrant.of_role(limited) == RoleGrant({AUDIT: AUDIT_READ}, audit_history_days=30)
    assert EffectivePermissions.from_role(unlimited).audit_history_days == 0
    assert RoleGrant.of_role(unlimited).audit_history_days == 0
