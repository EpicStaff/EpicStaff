from django.contrib.auth import get_user_model

from tables.models.rbac_models import Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.rbac_exceptions import (
    InactiveUserError,
    InvalidRoleAssignmentError,
    LastSuperadminError,
    SuperadminNotAssignableError,
)


class UserManagementGuards:
    """Pure invariant checks for Story 5.

    Static methods so they can be called without instance state. Each
    method is intended to run inside a service-level `transaction.atomic()`
    *after* the contested row has been `select_for_update()`-locked. The
    row lock + same-transaction count is what makes the checks race-safe;
    these methods themselves do not acquire locks.
    """

    @staticmethod
    def assert_not_last_active_superadmin(target_user) -> None:
        """Refuses if target_user is the only User row with
        is_superadmin=True AND is_active=True.

        Caller must have already SELECT FOR UPDATE'd the target_user row.
        """
        UserModel = get_user_model()
        if not (target_user.is_superadmin and target_user.is_active):
            return  # not currently a counting superadmin → revoke is a no-op
        active_superadmin_count = UserModel.objects.filter(
            is_superadmin=True, is_active=True
        ).count()
        if active_superadmin_count <= 1:
            raise LastSuperadminError()

    @staticmethod
    def assert_role_is_assignable(role: Role, org_id: int) -> None:
        """Refuses to assign roles that are not valid membership targets:

        - The global Superadmin role (`is_built_in=True, name='Superadmin'`)
          — superadmin is a User flag granted via grant-superadmin, never
          an org-membership role.
        - A custom role whose `org_id` is not None and != the target org.
          (Story 9 forward-compat; for Story 5 there are no custom roles
          but the guard is in place.)
        """
        if role.is_built_in and role.name == BuiltInRole.SUPERADMIN:
            raise InvalidRoleAssignmentError()
        if role.org_id is not None and role.org_id != org_id:
            raise InvalidRoleAssignmentError()

    @staticmethod
    def assert_user_is_assignable_member(target) -> None:
        """Refuses accounts that cannot hold a membership: a superadmin (the
        row would grant nothing they do not already have) and a deactivated
        account (it cannot sign in to use one). Superadmin is checked first —
        it is the structural reason, and reactivating would not change it."""
        if target.is_superadmin:
            raise SuperadminNotAssignableError()
        if not target.is_active:
            raise InactiveUserError()

    @staticmethod
    def assert_membership_holder_is_assignable(membership) -> None:
        """Refuses a role change on a membership held by a superadmin. Takes
        the membership so the check reads off the row the caller locked."""
        if membership.user.is_superadmin:
            raise SuperadminNotAssignableError()
