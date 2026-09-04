from typing import Optional

from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models.rbac_enums import Permission
from tables.services.rbac.cross_org_permission_resolver import (
    CrossOrgPermissionResolver,
)
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.rbac.rbac_exceptions import OrgMembershipRequiredError


class CrossOrgResourceService:
    """Reusable authorization skeleton for cross-org management resources
    (roles, memberships, organizations).

    The coarse door gate (holds the action in >=1 org) runs in the view
    (`HasResourcePermissionAnywhere`). These methods do the precise per-org
    work every such resource shares:

    - `resolve_readable_org_ids` — the set of orgs the caller may READ this
      resource in (None = superadmin / all), for cross-org lists.
    - `apply_org_scope` — filter a queryset to those orgs, honouring an
      explicit `?org_ids=` selection with a 403 fail-loud on a forbidden id.
    - `resolve_for_write` — resolve the caller's permissions in a row's org,
      turning a non-member into the resource's own 404 (no existence leak).
    - `assert_can` — the verb check (403 on failure).

    Subclasses set `rbac_resource_type` (a `ResourceType`) and
    `not_found_exception` (the resource's 404 exception class).
    """

    rbac_resource_type = None
    not_found_exception = None

    _resolver = PermissionResolver()
    _org_access = CrossOrgPermissionResolver()

    def resolve_readable_org_ids(self, actor, scopes=None) -> Optional[set]:
        """Org ids where `actor` may READ this resource. None = superadmin
        (no filter). `scopes` may be the door gate's per-request cache."""
        if getattr(actor, "is_superadmin", False):
            return None
        if scopes is None:
            scopes = self._org_access.resolve_all(user=actor)
        return {
            scope.org.id
            for scope in scopes
            if scope.effective.can(self.rbac_resource_type.value, Permission.READ)
        }

    def resolve_for_write(self, actor, row_org_id):
        """Resolve the caller's permissions in the row's org for a write. A
        non-member (or inactive org) surfaces as the resource's 404 — a row in
        an org the caller can't see is indistinguishable from a missing one.
        Superadmin short-circuits inside the resolver."""
        try:
            return self._resolver.resolve(user=actor, org_id=row_org_id)
        except OrgMembershipRequiredError as exc:
            raise self.not_found_exception() from exc

    def assert_can(self, effective, action) -> None:
        if not effective.can(self.rbac_resource_type.value, action):
            raise PermissionDenied("You do not have permission to perform this action.")

    def apply_org_scope(self, actor, org_ids, base_qs, org_field="org_id", scopes=None):
        """Filter `base_qs` to the caller's readable orgs. An explicit
        `org_ids` restricts to those ids; a forbidden id fails loud (403) for
        the whole request. `org_ids=None` = every readable org (superadmin =
        no filter). `org_field` is the queryset lookup to the org id."""
        readable = self.resolve_readable_org_ids(actor, scopes=scopes)
        if org_ids is not None:
            requested = set(org_ids)
            if readable is not None:
                forbidden = requested - readable
                if forbidden:
                    raise PermissionDenied(
                        f"You do not have permission to read "
                        f"{self.rbac_resource_type.value} in organization(s) "
                        f"{sorted(forbidden)}."
                    )
            effective_ids = requested
        else:
            effective_ids = readable
        if effective_ids is not None:
            base_qs = base_qs.filter(**{f"{org_field}__in": effective_ids})
        return base_qs
