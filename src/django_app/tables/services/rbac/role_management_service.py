"""RoleManagementService — read surface in this story; writes land
later (custom roles) with the BuiltInRoleImmutableError guard already
in place via `assert_mutable`.
"""

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
from tables.services.rbac.cross_org_permission_resolver import (
    CrossOrgPermissionResolver,
)
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.rbac.rbac_exceptions import (
    BuiltInRoleImmutableError,
    OrganizationNotFoundError,
    OrgMembershipRequiredError,
    PermissionEscalationError,
    RoleNameConflictError,
    RoleNotFoundError,
)


class RoleManagementService:
    _resolver = PermissionResolver()
    _org_access = CrossOrgPermissionResolver()

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
            self._assert_can(effective=effective, action=Permission.CREATE)
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
        `permissions`, if present, is a full replacement. Atomic + row-locked."""
        with transaction.atomic():
            role = self._get_locked_role(role_id=role_id)
            self.assert_mutable(role)
            effective = self._resolve_for_write(actor=actor, role=role)
            self._assert_can(effective=effective, action=Permission.UPDATE)
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
        effective = self._resolve_for_write(actor=actor, role=role)
        self._assert_can(effective=effective, action=Permission.DELETE)
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
            effective = self._resolve_for_write(actor=actor, role=role)
            self._assert_can(effective=effective, action=Permission.DELETE)
            viewer_role = Role.objects.get(
                name=BuiltInRole.VIEWER, is_built_in=True, org__isnull=True
            )
            reassigned = OrganizationUser.objects.filter(role_id=role.id).update(
                role_id=viewer_role.id
            )
            role.delete()
        return reassigned

    # ---- read authorization ----

    def get_role_for_read(self, actor, role_id) -> Role:
        """Fetch a role the actor is allowed to READ, with display data
        attached for serialization. Built-ins are visible to any principal
        with ROLES.READ anywhere; a custom role in an org the actor cannot
        READ raises RoleNotFoundError (404 — no existence leak)."""
        role, _ = self._get_role_with_read_access(actor=actor, role_id=role_id)
        self.attach_role_display(roles=[role])
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
        self.attach_role_display(roles=[role])
        return role

    # ---- cross-org list ----

    def list_built_in_roles(self) -> list[Role]:
        roles = list(
            Role.objects.filter(is_built_in=True, org__isnull=True)
            .order_by("name")
            .prefetch_related("permissions_set")
        )
        self.attach_role_display(roles=roles)
        return roles

    def list_custom_roles(self, actor, org_ids, scopes=None):
        """Return a queryset of custom roles across the orgs the actor may
        READ. `org_ids` (list) restricts to those orgs — a forbidden id
        raises PermissionDenied (fail-loud). `org_ids=None` means every
        readable org. Superadmin reads all orgs. `scopes` is the caller's
        pre-resolved cross-org scopes (from the door gate's per-request
        cache); when None the service resolves them itself."""
        is_superadmin = getattr(actor, "is_superadmin", False)
        if is_superadmin:
            readable = None  # all
        else:
            if scopes is None:
                scopes = self._org_access.resolve_all(user=actor)
            readable = {
                scope.org.id
                for scope in scopes
                if scope.effective.can(ResourceType.ROLES.value, Permission.READ)
            }

        if org_ids is not None:
            requested = set(org_ids)
            if not is_superadmin:
                forbidden = requested - readable
                if forbidden:
                    raise PermissionDenied(
                        f"You do not have permission to read roles in organization(s) "
                        f"{sorted(forbidden)}."
                    )
            effective_org_ids = requested
        else:
            effective_org_ids = readable  # None for superadmin → no filter

        qs = (
            Role.objects.filter(is_built_in=False)
            .select_related("org")
            .prefetch_related("permissions_set")
            .order_by("org__name", "name")
        )
        if effective_org_ids is not None:
            qs = qs.filter(org_id__in=effective_org_ids)
        return qs

    # ---- display attributes ----

    def attach_role_display(self, roles) -> None:
        """Attach `_perm_rows`, `_assigned_count`, `_effective_org_id` used
        by RoleResponseSerializer. Custom roles get their per-role count
        (a custom role lives in exactly one org, so the count is that org's).
        Built-ins get 0 — a global cross-org total would both leak an
        aggregate to a single-org caller and violate the response contract."""
        custom = [r for r in roles if not r.is_built_in]
        self._attach_assigned_counts(roles=custom, org_id=None)
        for role in roles:
            role._perm_rows = list(role.permissions_set.all())
            role._effective_org_id = role.org_id
            if role.is_built_in:
                role._assigned_count = 0

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

    def _resolve_for_write(self, actor, role):
        """Resolve the actor's permissions in the role's org for a write.

        A non-member (or inactive org) surfaces as RoleNotFoundError (404 —
        no existence leak), matching a role the caller cannot see, rather
        than a 403 that reveals the row exists in another org. Superadmin
        short-circuits inside the resolver. Note: this gates on membership,
        not READ — a role granting only CREATE/UPDATE/DELETE (without READ)
        can still be written by its holder."""
        try:
            return self._resolver.resolve(user=actor, org_id=role.org_id)
        except OrgMembershipRequiredError as exc:
            raise RoleNotFoundError() from exc

    def _assert_can(self, effective, action) -> None:
        """Verb gate: `effective` must include `action` on ROLES. Callers
        resolve once — which also raises OrgMembershipRequiredError for a
        non-member — and pass the result here. Superadmin's
        EffectivePermissions.can() returns True for every action."""
        if not effective.can(ResourceType.ROLES.value, action):
            raise PermissionDenied(
                "You do not have permission to manage roles in this organization."
            )

    def _assert_within_ceiling(self, effective, permissions) -> None:
        """Ceiling rule: every requested bit must be within the caller's own
        effective permissions. Takes an already-resolved `effective` from
        the caller. Superadmin bypasses."""
        if effective.is_superadmin:
            return
        for entry in permissions:
            caller_mask = effective.by_resource.get(entry["resource_type"], 0)
            if entry["bitmask"] & ~caller_mask:
                raise PermissionEscalationError()

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
