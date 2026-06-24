"""RoleManagementService — read surface in this story; writes land
later (custom roles) with the BuiltInRoleImmutableError guard already
in place via `assert_mutable`.
"""

from typing import Optional

from django.db.models import Count, Q

from tables.models.rbac_models import Organization, OrganizationUser, Role
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.rbac_exceptions import (
    BuiltInRoleImmutableError,
    OrganizationNotFoundError,
    RoleNotFoundError,
)


class RoleManagementService:
    def list_roles(self, org_id: Optional[int] = None):
        """Return built-in roles plus (optionally) `org_id`'s custom roles.

        Each Role row in the result has:
        - `_perm_rows`: list of RolePermission rows (prefetched).
        - `_assigned_count`: int (count of OrganizationUser referencing it,
          scoped to `org_id` when provided).
        - `_effective_org_id`: the org_id the response is contextualized to.
          Custom roles use their own org_id. Built-in templates (Org Admin /
          Member / Viewer) inherit the caller's active `org_id`. The global
          Superadmin role stays None — it doesn't belong to any org.

        Note: `_assigned_count` counts OrganizationUser rows with matching
        role_id only. It does NOT include `is_superadmin=True` users who
        lack a Superadmin membership row.
        """
        if org_id is not None:
            # Target-context callers (and superadmin via header) reach here
            # without a membership check guaranteeing the org exists — an
            # unknown id must 404, not silently return only the built-ins.
            # is_active is intentionally not filtered: superadmin may audit a
            # deactivated-but-existing org.
            if not Organization.objects.filter(pk=org_id).exists():
                raise OrganizationNotFoundError()
            role_filter = Q(is_built_in=True, org__isnull=True) | Q(org_id=org_id)
        else:
            role_filter = Q(is_built_in=True, org__isnull=True)
        qs = (
            Role.objects.filter(role_filter)
            .order_by("is_built_in", "name")
            .prefetch_related("permissions_set")
        )

        roles = list(qs)
        self._attach_assigned_counts(roles=roles, org_id=org_id)
        for role in roles:
            role._perm_rows = list(role.permissions_set.all())
            role._effective_org_id = self._derive_effective_org_id(
                role=role, context_org_id=org_id
            )
        return roles

    def get_role(self, role_id) -> Role:
        try:
            pk = int(role_id)
        except (TypeError, ValueError) as exc:
            raise RoleNotFoundError() from exc
        try:
            role = Role.objects.prefetch_related("permissions_set").get(pk=pk)
        except Role.DoesNotExist as exc:
            raise RoleNotFoundError() from exc
        self._attach_assigned_counts(roles=[role], org_id=role.org_id)
        role._perm_rows = list(role.permissions_set.all())
        return role

    def assert_mutable(self, role: Role) -> None:
        """Future write methods call this before update/delete. Shipped
        now so the rule 'edit/delete a built-in role is rejected' is
        satisfied immediately."""
        if role.is_built_in:
            raise BuiltInRoleImmutableError()

    @staticmethod
    def _derive_effective_org_id(
        role: Role, context_org_id: Optional[int]
    ) -> Optional[int]:
        """For custom roles, the row's own org_id is the source of truth.
        For built-in templates (Org Admin / Member / Viewer), the effective
        org_id is the caller's active context. For the global Superadmin
        role, None — it transcends any specific org."""
        if role.org_id is not None:
            return role.org_id
        if role.is_built_in and role.name == BuiltInRole.SUPERADMIN:
            return None
        return context_org_id

    @staticmethod
    def _attach_assigned_counts(roles, org_id: Optional[int]) -> None:
        role_ids = [r.id for r in roles]
        if not role_ids:
            return
        filters = {"role_id__in": role_ids}
        if org_id is not None:
            filters["org_id"] = org_id
        counts_qs = (
            OrganizationUser.objects.filter(**filters)
            .values("role_id")
            .annotate(c=Count("id"))
        )
        counts = {row["role_id"]: row["c"] for row in counts_qs}
        for role in roles:
            role._assigned_count = counts.get(role.id, 0)
