from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, QuerySet

from tables.models.rbac_models import Organization, OrganizationUser, User
from tables.models.rbac_models.rbac_enums import BuiltInRole, Permission, ResourceType
from tables.services.rbac.cross_org_service import CrossOrgResourceService
from tables.services.rbac.rbac_exceptions import (
    LastActiveOrganizationError,
    OrganizationNameConflictError,
    OrganizationNotFoundError,
)


class OrganizationManagementService(CrossOrgResourceService):
    """Read + write operations on Organization for the adaptive admin panel.

    The cross-org list / read / rename are permission-aware (ORGANIZATIONS
    bits); create / deactivate / reactivate stay superadmin-only (enforced at
    the view via `superadmin_actions`).

    Read methods return querysets annotated with `member_count`. Write methods
    are atomic. The "last active organization" guard is a private helper so
    that any future caller (CLI, async job) can reuse the same rule.
    """

    rbac_resource_type = ResourceType.ORGANIZATIONS
    not_found_exception = OrganizationNotFoundError

    def list_for_actor(
        self, actor, is_active=None, search=None, org_ids=None, scopes=None
    ) -> QuerySet[Organization]:
        """Permission-aware org list: superadmin sees all; everyone else sees
        the orgs where they hold ORGANIZATIONS.READ (a forbidden ?org_ids=
        entry fails loud, 403). Returns a queryset annotated with
        `member_count`, with each org's Org Admins prefetched into
        `_admin_memberships` (attach via `attach_admins`)."""
        admin_memberships_qs = (
            OrganizationUser.objects.filter(
                role__name=BuiltInRole.ORG_ADMIN, role__is_built_in=True
            )
            .select_related("user")
            .order_by("joined_at", "user_id")
        )
        base_qs = self._list_organizations(is_active=is_active).prefetch_related(
            Prefetch(
                "members",
                queryset=admin_memberships_qs,
                to_attr="_admin_memberships",
            )
        )
        qs = self.apply_org_scope(
            actor=actor, org_ids=org_ids, base_qs=base_qs, org_field="id", scopes=scopes
        )
        if search:
            qs = qs.filter(name__icontains=search)
        return qs

    def attach_admins(self, orgs, include_superadmin_fallback: bool):
        """Set `.admins` on each org from the prefetched `_admin_memberships`
        (Org Admin role holders, ordered joined_at/user_id).

        Business rule: when an org has zero Org Admins, superadmin viewers see
        a fallback of the oldest active superadmin (so the column is never
        empty for them); delegated admins never see that fallback — it would
        leak a superadmin identity. The fallback user is fetched at most once."""
        fallback_resolved = False
        fallback: list[User] = []
        for org in orgs:
            org.admins = [m.user for m in org._admin_memberships]
            if not org.admins and include_superadmin_fallback:
                if not fallback_resolved:
                    user = self._get_fallback_admin_user()
                    fallback = [user] if user is not None else []
                    fallback_resolved = True
                org.admins = fallback
        return orgs

    def get_for_read(self, actor, org_id) -> Organization:
        """Fetch one org for the settings/detail view. Requires
        ORGANIZATIONS.READ in that org (or superadmin); a non-member surfaces
        as OrganizationNotFoundError (404 — no existence leak)."""
        effective = self.resolve_for_write(actor, org_id)
        self.assert_can(effective, Permission.READ)
        return self._get_organization_with_member_count(org_id)

    def _list_organizations(
        self, is_active: bool | None = None
    ) -> QuerySet[Organization]:
        qs = Organization.objects.annotate(member_count=Count("members")).order_by(
            "-is_active", "name"
        )
        if is_active is not None:
            qs = qs.filter(is_active=is_active)
        return qs

    @transaction.atomic
    def create_organization(self, name: str) -> Organization:
        try:
            org = Organization.objects.create(name=name)
        except IntegrityError as exc:
            raise OrganizationNameConflictError() from exc
        return self._get_organization_with_member_count(org.pk)

    @transaction.atomic
    def rename_organization(self, actor, org_id: int, name: str) -> Organization:
        effective = self.resolve_for_write(actor, org_id)
        self.assert_can(effective, Permission.UPDATE)
        org = self._get_locked_org(org_id)
        if org.name == name:
            return self._get_organization_with_member_count(org.pk)
        org.name = name
        try:
            org.save(update_fields=["name", "updated_at"])
        except IntegrityError as exc:
            raise OrganizationNameConflictError() from exc
        return self._get_organization_with_member_count(org.pk)

    @transaction.atomic
    def deactivate_organization(self, org_id: int) -> Organization:
        org = self._get_locked_org(org_id)
        if not org.is_active:
            return self._get_organization_with_member_count(org.pk)
        self._assert_can_deactivate()
        org.is_active = False
        org.save(update_fields=["is_active", "updated_at"])
        return self._get_organization_with_member_count(org.pk)

    @transaction.atomic
    def reactivate_organization(self, org_id: int) -> Organization:
        org = self._get_locked_org(org_id)
        if org.is_active:
            return self._get_organization_with_member_count(org.pk)
        org.is_active = True
        org.save(update_fields=["is_active", "updated_at"])
        return self._get_organization_with_member_count(org.pk)

    def _get_organization_with_member_count(self, org_id: int) -> Organization:
        try:
            return self._list_organizations().get(pk=org_id)
        except Organization.DoesNotExist as exc:
            raise OrganizationNotFoundError() from exc

    def _get_fallback_admin_user(self) -> User | None:
        """Oldest active superadmin — fallback for orgs with no Org Admins
        in `list_organizations_with_admins`. Returns None if no active
        superadmin exists (theoretical edge case)."""
        return (
            User.objects.filter(is_superadmin=True, is_active=True)
            .order_by("created_at", "id")
            .first()
        )

    def _get_locked_org(self, org_id: int) -> Organization:
        """Row-locked fetch for write operations. Translates DoesNotExist
        into the project's standard 404 envelope so views don't need to
        know about Django's internal exception types."""
        try:
            return Organization.objects.select_for_update().get(pk=org_id)
        except Organization.DoesNotExist as exc:
            raise OrganizationNotFoundError() from exc

    @staticmethod
    def _assert_can_deactivate() -> None:
        """Refuses if `org` is the last active organization in the system.

        Run inside the same transaction as the deactivate write so the count
        is consistent with the SELECT FOR UPDATE on the org row. With per-row
        locking + a counted-rows query, two simultaneous deactivate calls
        cannot both succeed in driving the count to zero.
        """
        active_count = Organization.objects.filter(is_active=True).count()
        if active_count <= 1:
            raise LastActiveOrganizationError()
