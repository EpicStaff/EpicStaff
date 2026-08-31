from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Prefetch, QuerySet
from loguru import logger

from tables.models.rbac_models import OrganizationUser, Organization, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.rbac_exceptions import (
    EmailAlreadyExistsError,
    OrganizationNotFoundError,
    RoleNotFoundError,
    UserNotFoundError,
)
from tables.services.rbac.user_management_guards import UserManagementGuards


class UserManagementService:
    """Superadmin-only management of the global User account entity
    (list / create / grant-revoke superadmin / activate-deactivate).

    Membership management (add/change-role/remove within an org) is a
    separate, permission-driven surface — see MembershipManagementService.

    Every write method wraps in transaction.atomic(), acquires
    SELECT FOR UPDATE on the contested row before any guard, translates
    IntegrityError to typed domain exceptions, and logs INFO via loguru.
    """

    # ---- read ----

    def list_users(
        self,
        actor,
        email=None,
        is_superadmin=None,
        organization_id=None,
    ) -> QuerySet:
        """Cross-org user list. Caller is expected to be superadmin
        (enforced by the view permission class). The actor argument is
        accepted for symmetry and future audit logging — currently unused
        in the read path.
        """
        UserModel = get_user_model()
        qs = (
            UserModel.objects.all()
            .order_by("-created_at", "email")
            .prefetch_related(
                Prefetch(
                    "organization_memberships",
                    queryset=OrganizationUser.objects.select_related("org", "role"),
                )
            )
        )
        if email:
            qs = qs.filter(email__icontains=email)
        if is_superadmin is not None:
            qs = qs.filter(is_superadmin=is_superadmin)
        if organization_id is not None:
            qs = qs.filter(organization_memberships__org_id=organization_id).distinct()
        return qs

    # ---- create ----

    @transaction.atomic
    def create_user(
        self,
        actor,
        email,
        password,
        organization_id=None,
        role_id=None,
    ):
        """Creates a User. If `organization_id` is provided, also creates
        an OrganizationUser row in the same transaction.

          - role_id ignored when organization_id is None.
          - role_id defaults to built-in Member when organization_id is
            given without an explicit role_id (D9).
          - duplicate email → EmailAlreadyExistsError (400).
          - unknown organization_id → OrganizationNotFoundError (404).
          - unknown role_id → RoleNotFoundError (404).
          - non-assignable role → InvalidRoleAssignmentError (400).
        """
        UserModel = get_user_model()

        if organization_id is not None:
            try:
                org = Organization.objects.select_for_update().get(pk=organization_id)
            except Organization.DoesNotExist as exc:
                raise OrganizationNotFoundError() from exc
            role = self._resolve_role(role_id, default_org_id=organization_id)
            UserManagementGuards.assert_role_is_assignable(role, org_id=organization_id)
        else:
            org = None
            role = None

        try:
            user = UserModel.objects.create_user(email=email, password=password)
        except IntegrityError as exc:
            raise EmailAlreadyExistsError() from exc

        if org is not None and role is not None:
            OrganizationUser.objects.create(user=user, org=org, role=role)

        logger.info(
            "UserManagementService.create_user actor={actor} new_user={new} "
            "org={org} role={role}",
            actor=getattr(actor, "email", "system"),
            new=user.email,
            org=getattr(org, "name", None),
            role=getattr(role, "name", None),
        )
        return user

    # ---- superadmin flag ----

    @transaction.atomic
    def grant_superadmin(self, actor, target_user_id):
        """Sets is_superadmin=True on target_user_id. Idempotent if
        already True."""
        UserModel = get_user_model()
        try:
            target = UserModel.objects.select_for_update().get(pk=target_user_id)
        except UserModel.DoesNotExist as exc:
            raise UserNotFoundError() from exc

        if target.is_superadmin:
            return target  # no-op

        target.is_superadmin = True
        target.save(update_fields=["is_superadmin", "updated_at"])
        target.refresh_from_db()

        purged = self._purge_memberships(target)

        logger.info(
            "UserManagementService.grant_superadmin actor={a} target={t} "
            "memberships_purged={p}",
            a=getattr(actor, "email", "system"),
            t=target.email,
            p=purged,
        )
        return target

    @transaction.atomic
    def revoke_superadmin(self, actor, target_user_id):
        """Sets is_superadmin=False on target_user_id. Last-active-superadmin
        guard. Idempotent if already False."""
        UserModel = get_user_model()
        try:
            target = UserModel.objects.select_for_update().get(pk=target_user_id)
        except UserModel.DoesNotExist as exc:
            raise UserNotFoundError() from exc

        if not target.is_superadmin:
            return target  # no-op

        UserManagementGuards.assert_not_last_active_superadmin(target)

        target.is_superadmin = False
        target.save(update_fields=["is_superadmin", "updated_at"])
        target.refresh_from_db()

        logger.info(
            "UserManagementService.revoke_superadmin actor={a} target={t}",
            a=getattr(actor, "email", "system"),
            t=target.email,
        )
        return target

    @transaction.atomic
    def set_user_active(self, actor, target_user_id, is_active):
        """Set is_active on a user account (superadmin-only, gated at the
        view). Idempotent. Deactivating the last active superadmin is
        refused (reuses the last-active-superadmin guard)."""
        UserModel = get_user_model()
        try:
            target = UserModel.objects.select_for_update().get(pk=target_user_id)
        except UserModel.DoesNotExist as exc:
            raise UserNotFoundError() from exc

        if not is_active:
            UserManagementGuards.assert_not_last_active_superadmin(target)

        if target.is_active != is_active:
            target.is_active = is_active
            target.save(update_fields=["is_active", "updated_at"])
            target.refresh_from_db()

        logger.info(
            "UserManagementService.set_user_active actor={a} target={t} active={v}",
            a=getattr(actor, "email", "system"),
            t=target.email,
            v=is_active,
        )
        return target

    # ---- internal helpers ----

    @staticmethod
    def _purge_memberships(target) -> int:
        """A superadmin reaches every organization through the permission
        bypass, so a membership row grants nothing and its role is never read.
        Dropping them keeps the table honest. Revoking superadmin does not
        restore them — the account lands with no organizations."""
        _, per_model = OrganizationUser.objects.filter(user=target).delete()
        return per_model.get("tables.OrganizationUser", 0)

    def _resolve_role(self, role_id, default_org_id):
        """If role_id is None, returns the built-in Member role. Otherwise
        returns the Role with the given pk, raising RoleNotFoundError if
        absent.

        `default_org_id` is unused for built-in role lookup but kept in
        the signature so callers can pass it for future story extensions
        (custom default-role per org)."""
        if role_id is None:
            try:
                return Role.objects.get(
                    name=BuiltInRole.MEMBER, is_built_in=True, org__isnull=True
                )
            except Role.DoesNotExist as exc:
                raise RoleNotFoundError() from exc
        try:
            return Role.objects.get(pk=role_id)
        except Role.DoesNotExist as exc:
            raise RoleNotFoundError() from exc
