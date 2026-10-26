"""Checks other apps add to assigning a role, run after rbac's own escalation ceiling.

rbac's ceiling covers the permission catalog only. An app that gives roles authority rbac
does not store registers a check here at app load, so assigning a role can never hand out
that authority beyond the assigner's own, and rbac never imports the app.
"""

from typing import Protocol

from rbac.access.effective import EffectivePermissions
from rbac.models import Role


class RoleAssignmentCheck(Protocol):
    """Refuses a role assignment that would give authority the assigner does not hold."""

    def assert_assignable(
        self, *, effective: EffectivePermissions, role: Role, org_id: int
    ) -> None:
        """Raise `PermissionEscalationError` when `role` gives, in `org_id`, more than `effective` holds.

        `effective` is the assigner's own permissions in `org_id` (a SuperAdmin's when
        `effective.is_superadmin`).
        """
        ...


_checks: list[RoleAssignmentCheck] = []


def register_role_assignment_check(check: RoleAssignmentCheck) -> None:
    """Add a check every membership role assignment runs."""
    if any(type(registered) is type(check) for registered in _checks):
        raise ValueError(f"{type(check).__name__} is already registered")
    _checks.append(check)


def role_assignment_checks() -> tuple[RoleAssignmentCheck, ...]:
    """Return the registered checks in registration order."""
    return tuple(_checks)


def assert_role_assignment_allowed(
    *, effective: EffectivePermissions, role: Role, org_id: int
) -> None:
    """Run every registered check on assigning `role` in `org_id`.

    Call it right after `assert_within_ceiling` wherever a membership's role is set by an
    actor, inside the same transaction.

    Raises:
        PermissionEscalationError: A check found authority beyond the assigner's own.
    """
    for check in _checks:
        check.assert_assignable(effective=effective, role=role, org_id=org_id)
