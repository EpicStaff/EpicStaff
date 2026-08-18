from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import Q
from loguru import logger

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.cross_org_service import CrossOrgResourceService
from tables.services.rbac.rbac_exceptions import (
    MembershipAlreadyExistsError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
    OrgMembershipRequiredError,
    RoleNotFoundError,
    SelfMembershipModificationError,
    UserNotFoundError,
)
from tables.services.rbac.user_management_guards import UserManagementGuards


class MembershipManagementService(CrossOrgResourceService):
    """Cross-org membership management (add / change-role / remove), gated by
    the USERS permission per org. Extends the cross-org skeleton: the coarse
    door gate runs in the view; the precise per-org checks run here.

    Account creation is NOT here — it stays a superadmin-only operation on
    /api/admin/users/. `add_member` only LINKS an existing account.

    Invariants (per the spec):
      - No general assignment ceiling — any existing role may be assigned to
        others (assert_role_is_assignable still blocks the global Superadmin
        role and foreign-org custom roles).
      - A non-superadmin cannot change or remove their OWN membership.
      - No last-org-admin guard — superadmin is the rescue backstop.
    """

    rbac_resource_type = ResourceType.USERS
    not_found_exception = MembershipNotFoundError

    # ---- read ----

    def list_memberships(
        self, actor, org_ids, search=None, role_id=None, status_value=None, scopes=None
    ):
        """Cross-org membership rows the actor may READ. Filtering by
        `search` (email/display_name), `role_id`, and `status`
        (active/inactive account). Ordering is applied by the view."""
        base_qs = OrganizationUser.objects.select_related("user", "org", "role")
        qs = self.apply_org_scope(
            actor=actor,
            org_ids=org_ids,
            base_qs=base_qs,
            org_field="org_id",
            scopes=scopes,
        )
        if search:
            qs = qs.filter(
                Q(user__email__icontains=search)
                | Q(user__display_name__icontains=search)
            )
        if role_id is not None:
            qs = qs.filter(role_id=role_id)
        if status_value == "active":
            qs = qs.filter(user__is_active=True)
        elif status_value == "inactive":
            qs = qs.filter(user__is_active=False)
        return qs

    # ---- create (link an existing user) ----

    @transaction.atomic
    def add_member(self, actor, org_id, email, user_id, role_id):
        """Link an existing user to `org_id` with `role_id`. Unknown
        email/user_id → UserNotFoundError (404); already a member →
        MembershipAlreadyExistsError (400)."""
        effective = self._resolve_org_for_add(actor, org_id)
        self.assert_can(effective, Permission.CREATE)
        if not Organization.objects.filter(pk=org_id).exists():
            raise OrganizationNotFoundError()
        target = self._resolve_target_user(email=email, user_id=user_id)
        role = self._resolve_role(role_id)
        UserManagementGuards.assert_role_is_assignable(role, org_id=org_id)
        if OrganizationUser.objects.filter(user=target, org_id=org_id).exists():
            raise MembershipAlreadyExistsError()
        try:
            membership = OrganizationUser.objects.create(
                user=target, org_id=org_id, role=role
            )
        except IntegrityError as exc:
            # Pre-check above covers the common duplicate; reaching here means a
            # concurrent insert of the same (user, org) — still a duplicate.
            raise MembershipAlreadyExistsError() from exc
        logger.info(
            "MembershipManagementService.add_member actor={a} user={u} "
            "org={o} role={r}",
            a=getattr(actor, "email", "system"),
            u=target.email,
            o=org_id,
            r=role.name,
        )
        return self._refetch(membership.pk)

    # ---- update role ----

    @transaction.atomic
    def change_role(self, actor, membership_id, role_id):
        """Change a member's role. Cross-org membership → 404 (no-leak);
        own membership → 403 (self-mutation blocked); member lacking the
        USERS.UPDATE bit → 403."""
        membership = self._get_membership_locked(membership_id)
        effective = self.resolve_for_write(actor, membership.org_id)  # no-leak 404
        self._assert_not_self(actor, membership)
        self.assert_can(effective, Permission.UPDATE)
        new_role = self._resolve_role(role_id)
        UserManagementGuards.assert_role_is_assignable(
            new_role, org_id=membership.org_id
        )
        if membership.role_id != new_role.pk:
            membership.role = new_role
            membership.save(update_fields=["role"])
        logger.info(
            "MembershipManagementService.change_role actor={a} membership={m} "
            "role={r}",
            a=getattr(actor, "email", "system"),
            m=membership_id,
            r=new_role.name,
        )
        return self._refetch(membership.pk)

    # ---- delete ----

    @transaction.atomic
    def remove_member(self, actor, membership_id):
        """Remove a membership. Cross-org → 404; own → 403; lacking
        USERS.DELETE → 403. No last-org-admin guard by design."""
        membership = self._get_membership_locked(membership_id)
        effective = self.resolve_for_write(actor, membership.org_id)  # no-leak 404
        self._assert_not_self(actor, membership)
        self.assert_can(effective, Permission.DELETE)
        membership.delete()
        logger.info(
            "MembershipManagementService.remove_member actor={a} membership={m}",
            a=getattr(actor, "email", "system"),
            m=membership_id,
        )

    # ---- internals ----

    def _resolve_org_for_add(self, actor, org_id):
        """Precise per-org check for add — org comes from the body, not a
        row. A caller who is not a member of org_id (and not superadmin)
        cannot see it → OrganizationNotFoundError (404, no existence leak)."""
        try:
            return self._resolver.resolve(user=actor, org_id=org_id)
        except OrgMembershipRequiredError as exc:
            raise OrganizationNotFoundError() from exc

    @staticmethod
    def _get_membership_locked(membership_id):
        membership = (
            OrganizationUser.objects.select_for_update(of=["self"])
            .select_related("org", "role")
            .filter(pk=membership_id)
            .first()
        )
        if membership is None:
            raise MembershipNotFoundError()
        return membership

    @staticmethod
    def _assert_not_self(actor, membership):
        if getattr(actor, "is_superadmin", False):
            return
        if getattr(actor, "id", None) == membership.user_id:
            raise SelfMembershipModificationError()

    @staticmethod
    def _resolve_target_user(email, user_id):
        UserModel = get_user_model()
        if user_id is not None:
            user = UserModel.objects.filter(pk=user_id).first()
        else:
            user = UserModel.objects.filter(email__iexact=email).first()
        if user is None:
            raise UserNotFoundError()
        return user

    @staticmethod
    def _resolve_role(role_id):
        role = Role.objects.filter(pk=role_id).first()
        if role is None:
            raise RoleNotFoundError()
        return role

    @staticmethod
    def _refetch(membership_pk):
        return OrganizationUser.objects.select_related("user", "org", "role").get(
            pk=membership_pk
        )
