"""RoleManagementService — read surface in this story; writes land
later (custom roles) with the BuiltInRoleImmutableError guard already
in place via `assert_mutable`.
"""

from collections import defaultdict
from typing import Optional

from django.db import transaction
from django.db.models import Count
from rest_framework.exceptions import PermissionDenied

from tables.models.rbac_models import (
    Organization,
    OrganizationUser,
    Role,
    RolePermission,
)
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType
from tables.services.rbac.cross_org_service import CrossOrgResourceService
from tables.services.rbac.effective_permissions import EffectivePermissions
from tables.services.rbac.permission_assert import assert_within_ceiling
from tables.services.rbac.user_management_guards import UserManagementGuards
from tables.services.rbac.rbac_exceptions import (
    BuiltInRoleImmutableError,
    OrganizationNotFoundError,
    OrgMembershipRequiredError,
    RoleNameConflictError,
    RoleNotFoundError,
)


class RoleManagementService(CrossOrgResourceService):
    rbac_resource_type = ResourceType.ROLES
    not_found_exception = RoleNotFoundError

    def assert_mutable(self, role: Role) -> None:
        """Future write methods call this before update/delete. Shipped
        now so the rule 'edit/delete a built-in role is rejected' is
        satisfied immediately."""
        if role.is_built_in:
            raise BuiltInRoleImmutableError()

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

    # ---- writes ----

    def create_role(self, actor, org_id, name, description, permissions) -> Role:
        """Create an org-scoped custom role. `permissions` is a list of
        {resource_type, bitmask}. Enforces the ceiling rule and per-org
        CREATE. Atomic."""
        with transaction.atomic():
            effective = self._resolver.resolve(user=actor, org_id=org_id)
            self.assert_can(effective=effective, action=Permission.CREATE)
            self._assert_within_ceiling(effective=effective, permissions=permissions)
            self._assert_name_available(org_id=org_id, name=name, exclude_role_id=None)
            # For non-superadmin callers the resolve() above already proved
            # membership (hence the org exists). Superadmin skips that check, so
            # guard here to turn a bad org_id into a 404 instead of an FK
            # IntegrityError (500).
            if not Organization.objects.filter(pk=org_id).exists():
                raise OrganizationNotFoundError()
            role = Role.objects.create(
                name=name, description=description, org_id=org_id, is_built_in=False
            )
            self._write_permission_rows(role=role, permissions=permissions)
        return self._build_role_response(role_id=role.id)

    def update_role(self, actor, role_id, changes) -> Role:
        """Apply a partial update (subset of name/description/permissions).
        `permissions`, if present, is a full replacement. Atomic + row-locked.

        A role the caller cannot see raises RoleNotFoundError (404) from
        `resolve_for_write`, so this endpoint never confirms an id that the
        detail route reports as missing; only a visible role can reach the
        403 from `assert_can`. Built-ins short-circuit before either check —
        they are visible to every caller, so their 403 leaks nothing."""
        with transaction.atomic():
            role = self._get_locked_role(role_id=role_id)
            self.assert_mutable(role)
            effective = self.resolve_for_write(
                actor, role.org_id, action=Permission.UPDATE
            )
            self.assert_can(effective=effective, action=Permission.UPDATE)
            if "permissions" in changes:
                self._assert_within_ceiling(
                    effective=effective, permissions=changes["permissions"]
                )
            if "name" in changes:
                self._assert_name_available(
                    org_id=role.org_id, name=changes["name"], exclude_role_id=role.id
                )
                role.name = changes["name"]
            if "description" in changes:
                role.description = changes["description"]
            role.save(update_fields=["name", "description", "updated_at"])
            if "permissions" in changes:
                role.permissions_set.all().delete()
                self._write_permission_rows(
                    role=role, permissions=changes["permissions"]
                )
        return self._build_role_response(role_id=role.id)

    def preview_delete(self, actor, role_id) -> dict:
        """Dry-run: report the memberships that a delete would reassign to
        Viewer. No mutation.

        Uses the same authorization as `delete_role` — membership in the
        role's org (404 otherwise, no existence leak) plus the DELETE verb —
        so the preview never disagrees with the real delete. Read-only, so
        the role is fetched without a row lock."""
        role = self._fetch_role_or_404(role_id=role_id)
        self.assert_mutable(role)
        effective = self.resolve_for_write(actor, role.org_id, action=Permission.DELETE)
        self.assert_can(effective=effective, action=Permission.DELETE)
        memberships = OrganizationUser.objects.filter(role_id=role.id).select_related(
            "user"
        )
        affected = [
            {
                "user_id": m.user_id,
                "email": m.user.email,
                "display_name": m.user.display_name,
            }
            for m in memberships
        ]
        return {
            "role_id": role.id,
            "assigned_count": len(affected),
            "affected_users": affected,
        }

    def delete_role(self, actor, role_id) -> int:
        """Reassign every member to the built-in Viewer role, then delete
        the role. Members are never evicted. Returns the reassigned count.
        Atomic + row-locked."""
        with transaction.atomic():
            role = self._get_locked_role(role_id=role_id)
            self.assert_mutable(role)
            effective = self.resolve_for_write(
                actor, role.org_id, action=Permission.DELETE
            )
            self.assert_can(effective=effective, action=Permission.DELETE)
            viewer_role = Role.objects.get(
                name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True
            )
            reassigned = OrganizationUser.objects.filter(role_id=role.id).update(
                role_id=viewer_role.id
            )
            role.delete()
        return reassigned

    # ---- read authorization ----

    def get_role_for_read(self, actor, role_id, scopes=None) -> Role:
        """Fetch a role the actor is allowed to READ, with display data
        attached for serialization. Built-ins are visible to any principal
        with ROLES.READ anywhere; a custom role in an org the actor cannot
        READ raises RoleNotFoundError (404 — no existence leak).

        `scopes` is the caller's pre-resolved cross-org scopes from the door
        gate's per-request cache. Only a built-in target needs them: a custom
        role is counted in its own org, so resolving them would be a wasted
        query. The custom branch passes `scope_org_ids=set()` rather than
        `None`: only built-in counting ever consults that argument, and no
        built-in can reach this branch, but an empty selection fails closed
        — counting nothing rather than everything — if that assumption is
        ever wrong."""
        role, _ = self._get_role_with_read_access(actor=actor, role_id=role_id)
        scope_org_ids = (
            self.resolve_scope_org_ids(actor, org_ids=None, scopes=scopes)
            if role.is_built_in
            else set()
        )
        self.attach_role_display(roles=[role], scope_org_ids=scope_org_ids)
        return role

    def _get_role_with_read_access(self, actor, role_id):
        """Fetch a role the actor may READ; return (role, effective).

        `effective` is the caller's EffectivePermissions in the role's org,
        or None when no per-org resolve was needed — superadmin, or a
        built-in role (both visible without an org-scoped check). Raises
        RoleNotFoundError for a missing role, or one in an org the actor
        cannot READ (404 — no existence leak). Does NOT attach display
        data. Returning `effective` lets a caller (e.g. preview_delete)
        reuse the same resolve for a further verb check instead of
        resolving the (actor, org) pair again."""
        try:
            pk = int(role_id)
        except (TypeError, ValueError) as exc:
            raise RoleNotFoundError() from exc
        try:
            role = (
                Role.objects.select_related("org")
                .prefetch_related("permissions_set")
                .get(pk=pk)
            )
        except Role.DoesNotExist as exc:
            raise RoleNotFoundError() from exc

        if getattr(actor, "is_superadmin", False) or role.is_built_in:
            return role, None

        try:
            effective = self._resolver.resolve(user=actor, org_id=role.org_id)
        except OrgMembershipRequiredError as exc:
            raise RoleNotFoundError() from exc
        if not effective.can(ResourceType.ROLES.value, Permission.READ):
            raise RoleNotFoundError()
        return role, effective

    def _build_role_response(self, role_id) -> Role:
        """Fetch a role for a WRITE response without re-authorizing reads.
        The caller already passed the create/update authorization; the
        response must not re-apply the READ gate (a role granting
        CREATE/UPDATE without READ would otherwise 404 a committed write)."""
        role = (
            Role.objects.select_related("org")
            .prefetch_related("permissions_set")
            .get(pk=role_id)
        )
        # Only create/update reach here, and `assert_mutable` rejects a
        # built-in before either write begins. Only built-in counting consults
        # the scope. A custom role is counted in its own org,
        # which is exactly right for a write response even when the caller
        # holds CREATE/UPDATE without READ there.
        self.attach_role_display(roles=[role], scope_org_ids=set())
        return role

    # ---- cross-org list ----

    def list_built_in_roles(self, scope_org_ids, assignable_in=None) -> list[Role]:
        """The four built-in templates. `assignable_in` (a
        {org_id: EffectivePermissions} map, or None for no filtering) keeps
        only the ones the caller may assign — by **union** across the
        requested orgs, since the list is global while assignability is
        per-org. A single requested org therefore gives an exact answer and
        several give a superset.

        `scope_org_ids` (`Optional[set[int]]`, required) is forwarded to
        `attach_role_display` for the holder count: `None` means no filter at
        all (superadmin, count every organization), `set()` means an empty
        selection (count nothing) — the two are opposites, never test one by
        truthiness."""
        roles = list(
            Role.objects.filter(is_built_in=True, org__isnull=True)
            .order_by("name")
            .prefetch_related("permissions_set")
        )
        if assignable_in is not None:
            roles = [
                role
                for role in roles
                if any(
                    self.is_assignable_by(effective, role, org_id)
                    for org_id, effective in assignable_in.items()
                )
            ]
        self.attach_role_display(roles=roles, scope_org_ids=scope_org_ids)
        return roles

    def is_assignable_by(self, effective, role, org_id) -> bool:
        """Whether `effective` may assign `role` in `org_id`: a structurally
        valid membership target, and within the caller's escalation ceiling.

        The boolean twin of the two assertions `MembershipManagementService`
        runs before a write, so the picker cannot offer a role the write
        would refuse."""
        return UserManagementGuards.role_is_assignable(
            role, org_id
        ) and effective.covers(EffectivePermissions.bits_of(role))

    def resolve_assignable_scopes(self, actor, org_ids, scopes=None):
        """{org_id: EffectivePermissions} for the assignability filter, or None
        when no filtering applies — the parameter was absent, or the caller is
        a superadmin who may assign anything.

        Reuses the door gate's per-request `_rbac_org_scopes` cache, so the
        filter costs no additional query."""
        if org_ids is None or getattr(actor, "is_superadmin", False):
            return None
        if scopes is None:
            scopes = self._org_access.resolve_all(user=actor)
        requested = set(org_ids)
        return {
            scope.org.id: scope.effective
            for scope in scopes
            if scope.org.id in requested
        }

    def list_custom_roles(self, actor, org_ids, scopes=None, assignable_in=None):
        """Return a queryset of custom roles across the orgs the actor may
        READ. `org_ids` (list) restricts to those orgs — a forbidden id
        raises PermissionDenied (fail-loud). `org_ids=None` means every
        readable org. Superadmin reads all orgs. `scopes` is the caller's
        pre-resolved cross-org scopes (from the door gate's per-request
        cache); when None the base resolves them itself."""
        base_qs = (
            Role.objects.filter(is_built_in=False)
            .select_related("org")
            .prefetch_related("permissions_set")
            .order_by("org__name", "name")
        )
        scoped = self.apply_org_scope(
            actor=actor,
            org_ids=org_ids,
            base_qs=base_qs,
            org_field="org_id",
            scopes=scopes,
        )
        if assignable_in is None:
            return scoped
        # Each custom role lives in exactly one org, so it is compared there.
        # Filtered in Python because a bitmask-subset test across a role's
        # several permission rows is not a clean SQL predicate, and before
        # pagination so pages stay full and consistent. The candidate set is
        # only the requested orgs' custom roles.
        return [
            role
            for role in scoped
            if role.org_id in assignable_in
            and self.is_assignable_by(assignable_in[role.org_id], role, role.org_id)
        ]

    # ---- display attributes ----

    def attach_role_display(self, roles, scope_org_ids) -> None:
        """Attach `_perm_rows`, `_effective_org_id`, `_assigned_count` and
        `_assigned_by_org`, all read by RoleResponseSerializer.

        `scope_org_ids` is required rather than defaulted on purpose: a
        built-in role is one row shared by every org, so a call site that
        omitted the scope would publish a global cross-org total. `None` means
        no filter (superadmin); an empty set means no org is in scope. This
        mirrors `resolve_for_write`, whose `action` is required so that every
        call site states which verb it authorizes.

        Custom roles ignore the scope: a custom role's holders can only be in
        its own org, and the caller was already authorized against that role
        there.
        """
        custom = [role for role in roles if not role.is_built_in]
        built_in = [role for role in roles if role.is_built_in]
        self._attach_assigned_counts(roles=custom, org_id=None)
        self._attach_custom_assigned_breakdown(roles=custom)
        self._attach_built_in_assigned_counts(
            roles=built_in, scope_org_ids=scope_org_ids
        )
        for role in roles:
            role._perm_rows = list(role.permissions_set.all())
            role._effective_org_id = role.org_id

    @staticmethod
    def _attach_custom_assigned_breakdown(roles) -> None:
        """The one-entry breakdown for a custom role. Needs no query: the org
        is the role's own, `_attach_assigned_counts` has already counted it,
        and `role.org` is select_related by every caller."""
        for role in roles:
            count = getattr(role, "_assigned_count", 0)
            role._assigned_by_org = (
                [{"org": {"id": role.org_id, "name": role.org.name}, "count": count}]
                if role.org_id is not None and count
                else []
            )

    @staticmethod
    def _attach_built_in_assigned_counts(roles, scope_org_ids) -> None:
        """Per-org holder counts for built-in roles, restricted to
        `scope_org_ids` (`None` = every org).

        The Superadmin row is excluded. Its authority is the
        `User.is_superadmin` flag, so the only memberships carrying that role
        are the bootstrap rows migration 0211 deliberately retained -- a count
        over them reports how many bootstrap rows survived a migration, not how
        many superadmins exist. It would also tell a delegated admin that a
        platform superadmin is attached to their org, which `attach_admins`
        withholds for the same reason.

        Ordering is applied in Python, not by the query: `.values().annotate()`
        groups by the `values()` fields, so an `order_by(Lower("org__name"))`
        would pull that expression into the GROUP BY.
        """
        for role in roles:
            role._assigned_count = 0
            role._assigned_by_org = []
        countable = [role for role in roles if role.name != BuiltInRole.SUPERADMIN]
        if not countable or (scope_org_ids is not None and not scope_org_ids):
            return
        rows = OrganizationUser.objects.filter(
            role_id__in=[role.id for role in countable]
        )
        if scope_org_ids is not None:
            rows = rows.filter(org_id__in=scope_org_ids)
        by_role = defaultdict(list)
        for row in rows.values("role_id", "org_id", "org__name").annotate(
            c=Count("id")
        ):
            by_role[row["role_id"]].append(
                {
                    "org": {"id": row["org_id"], "name": row["org__name"]},
                    "count": row["c"],
                }
            )
        for role in countable:
            entries = sorted(
                by_role.get(role.id, []), key=lambda entry: entry["org"]["name"].lower()
            )
            role._assigned_by_org = entries
            role._assigned_count = sum(entry["count"] for entry in entries)

    # ---- internals ----

    def _get_locked_role(self, role_id) -> Role:
        try:
            pk = int(role_id)
        except (TypeError, ValueError) as exc:
            raise RoleNotFoundError() from exc
        try:
            return Role.objects.select_for_update().get(pk=pk)
        except Role.DoesNotExist as exc:
            raise RoleNotFoundError() from exc

    def _fetch_role_or_404(self, role_id) -> Role:
        """Non-locking role fetch for read-only paths (e.g. preview_delete).
        A bad or missing id surfaces as RoleNotFoundError (404)."""
        try:
            pk = int(role_id)
        except (TypeError, ValueError) as exc:
            raise RoleNotFoundError() from exc
        try:
            return Role.objects.get(pk=pk)
        except Role.DoesNotExist as exc:
            raise RoleNotFoundError() from exc

    def assert_can(self, effective, action) -> None:
        """Verb gate override with a roles-specific message. `effective` must
        include `action` on ROLES. Callers resolve once — which also raises
        OrgMembershipRequiredError for a non-member — and pass the result here.
        Superadmin's EffectivePermissions.can() returns True for every action."""
        if not effective.can(ResourceType.ROLES.value, action):
            raise PermissionDenied(
                "You do not have permission to manage roles in this organization."
            )

    def _assert_within_ceiling(self, effective, permissions) -> None:
        """Ceiling rule for authoring: every requested bit must be within the
        caller's own effective permissions. Adapts the validator's
        `[{resource_type, bitmask}]` shape onto the shared assertion, which
        role assignment uses too. Collapsing the list into a mapping cannot
        lose an entry -- RoleValidationService rejects a duplicate
        resource_type. Superadmin bypasses."""
        assert_within_ceiling(
            effective, {e["resource_type"]: e["bitmask"] for e in permissions}
        )

    @staticmethod
    def _assert_name_available(org_id, name, exclude_role_id) -> None:
        clash = Role.objects.filter(org_id=org_id, name__iexact=name)
        if exclude_role_id is not None:
            clash = clash.exclude(pk=exclude_role_id)
        if clash.exists():
            raise RoleNameConflictError()

    @staticmethod
    def _write_permission_rows(role, permissions) -> None:
        RolePermission.objects.bulk_create(
            [
                RolePermission(
                    role=role,
                    resource_type=entry["resource_type"],
                    permissions=entry["bitmask"],
                )
                for entry in permissions
            ]
        )
