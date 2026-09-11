from typing import Iterable, Optional

from django.db.models import Q
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models.rbac_enums import Permission
from tables.services.rbac.cross_org_permission_resolver import (
    CrossOrgPermissionResolver,
    OrgScope,
)
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.rbac.rbac_exceptions import OrgMembershipRequiredError


class CrossOrgResourceService:
    """Reusable authorization skeleton for cross-org management resources
    (roles, memberships, organizations, API keys).

    The coarse door gate (holds the action in >=1 org) runs in the view
    (`HasResourcePermissionAnywhere`). These methods do the precise per-org
    work every such resource shares:

    - `resolve_readable_org_ids` — the set of orgs the caller may READ this
      resource in (None = superadmin / all), for cross-org lists.
    - `apply_org_scope` — filter a queryset to those orgs, honouring an
      explicit `?org_ids=` selection with a 403 fail-loud on a forbidden id.
    - `resolve_for_write` — resolve the caller's permissions in a row's org,
      turning an invisible row into the resource's own 404 (no existence leak).
    - `authorize_any_org` — like `resolve_for_write`, for a row scoped
      through a set of orgs rather than a single org column.
    - `assert_visible` — the visibility check (404 on failure).
    - `assert_can` — the verb check (403 on failure).
    - `delegated_scope_q` — optional extra `Q` filter `apply_org_scope`
      applies for non-superadmins (e.g. an owner-membership join).

    Subclasses set `rbac_resource_type` (a `ResourceType`) and
    `not_found_exception` (the resource's 404 exception class).
    """

    rbac_resource_type = None
    not_found_exception = None
    delegated_scope_q: Optional[Q] = None

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

    def resolve_for_write(self, actor, row_org_id, action: Permission):
        """Resolve the caller's permissions in the row's org for `action`.

        Two conditions make the row indistinguishable from a missing one, and
        both raise the resource's 404: the caller is not a member of the row's
        org (or it is inactive), and the caller is a member who can neither
        READ the resource there nor perform `action` on it. Only once the row
        is visible may the caller's `assert_can` return 403 — a 403 on an
        invisible row would confirm an id the read surface denies.

        `action` is required: it is what separates a row the caller may not
        see from one they may see but not touch, so every call site has to
        state which verb it is authorizing. Superadmin short-circuits inside
        the resolver and inside `EffectivePermissions.can`.
        """
        try:
            effective = self._resolver.resolve(user=actor, org_id=row_org_id)
        except OrgMembershipRequiredError as exc:
            raise self.not_found_exception() from exc
        self.assert_visible(effective=effective, action=action)
        return effective

    def assert_visible(self, effective, action: Permission) -> None:
        """Raise the resource's 404 unless the row is visible to `effective`.

        Visible means READ **or** the action being attempted. READ is the
        ordinary way to see a row; holding the verb without READ is the
        deliberate write-without-read grant, which must keep working rather
        than 404 on a row it is authorized to change.
        """
        resource = self.rbac_resource_type.value
        if effective.can(resource, Permission.READ) or effective.can(resource, action):
            return
        raise self.not_found_exception()

    def authorize_any_org(
        self,
        actor,
        org_ids: Iterable[int],
        action: Permission,
        scopes: Optional[list[OrgScope]] = None,
    ) -> None:
        """Authorize a row scoped through a set of orgs rather than one column.

        Visibility decides the 404, the permission bit decides the 403 — the
        same split as `resolve_for_write`, which is this method with one org,
        applied existentially: the row is visible when at least one reachable
        org grants READ or `action`, and authorized when at least one grants
        `action`.
        """
        if getattr(actor, "is_superadmin", False):
            return
        if scopes is None:
            scopes = self._org_access.resolve_all(user=actor)
        requested: set[int] = set(org_ids)
        reachable: list[OrgScope] = [s for s in scopes if s.org.id in requested]
        if not reachable:
            raise self.not_found_exception()
        resource: str = self.rbac_resource_type.value
        if not any(scope.effective.can(resource, action) for scope in reachable):
            if not any(
                scope.effective.can(resource, Permission.READ) for scope in reachable
            ):
                raise self.not_found_exception()
            raise PermissionDenied("You do not have permission to perform this action.")

    def assert_can(self, effective, action) -> None:
        if not effective.can(self.rbac_resource_type.value, action):
            raise PermissionDenied("You do not have permission to perform this action.")

    def resolve_scope_org_ids(self, actor, org_ids, scopes=None) -> Optional[set[int]]:
        """The org ids this request is scoped to.

        An explicit `org_ids` selection wins; an entry the actor cannot READ
        fails the whole request (403 fail-loud) rather than silently narrowing
        it. Otherwise every org where the actor may READ this resource.

        `None` means no filter at all -- a superadmin -- and is NOT the same as
        an empty set, which scopes the request to no org. Callers must test
        `is None`, never truthiness: `?org_ids=,` parses to an empty selection,
        and treating that as "unfiltered" would publish a cross-org total.
        """
        return self._narrow_to_requested(
            readable=self.resolve_readable_org_ids(actor, scopes=scopes),
            org_ids=org_ids,
        )

    def _narrow_to_requested(self, readable, org_ids) -> Optional[set[int]]:
        """Apply an explicit `org_ids` selection to the readable set.

        Stated once so `apply_org_scope` (which filters a queryset) and
        `resolve_scope_org_ids` (which hands the same set to a counter) cannot
        disagree about which orgs a request covers.
        """
        if org_ids is None:
            return readable
        requested = set(org_ids)
        if readable is not None:
            forbidden = requested - readable
            if forbidden:
                raise PermissionDenied(
                    f"You do not have permission to read "
                    f"{self.rbac_resource_type.value} in organization(s) "
                    f"{sorted(forbidden)}."
                )
        return requested

    def apply_org_scope(self, actor, org_ids, base_qs, org_field="org_id", scopes=None):
        """Filter `base_qs` to the caller's readable orgs. An explicit
        `org_ids` restricts to those ids; a forbidden id fails loud (403) for
        the whole request. `org_ids=None` = every readable org (superadmin =
        no filter). `org_field` is the queryset lookup to the org id."""
        readable = self.resolve_readable_org_ids(actor, scopes=scopes)
        if readable is not None and self.delegated_scope_q is not None:
            base_qs = base_qs.filter(self.delegated_scope_q)
        effective_ids = self._narrow_to_requested(readable=readable, org_ids=org_ids)
        if effective_ids is not None:
            base_qs = base_qs.filter(**{f"{org_field}__in": effective_ids})
        return base_qs
