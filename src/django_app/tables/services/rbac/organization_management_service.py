from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, QuerySet

from tables.models.rbac_models import Organization, OrganizationUser, User
from tables.models.rbac_models.rbac_enums import BuiltInRole
from tables.services.rbac.rbac_exceptions import (
    LastActiveOrganizationError,
    OrganizationNameConflictError,
    OrganizationNotFoundError,
)


class OrganizationManagementService:
    """All read + write operations on Organization for the superadmin
    admin panel.

    Read methods return querysets annotated with `member_count`. Write methods
    are atomic. The "last active organization" guard is a private helper so
    that any future caller (CLI, async job) can reuse the same rule.
    """

    def list_organizations_with_admins(
        self, is_active: bool | None = None
    ) -> list[Organization]:
        """Public read for GET /api/admin/organizations/.

        Returns orgs annotated with `member_count`, ordered as in
        `_list_organizations`, with each org carrying an `admins` attribute:
        a list of `User` instances who hold the built-in `Org Admin` role
        in that org (ordered by `joined_at, user_id`).

        Business rule: if an org has zero Org Admin memberships, its
        `admins` attribute falls back to `[oldest_active_superadmin]`. If
        no active superadmin exists, the attribute is `[]`. The fallback
        user is fetched at most once per call, lazily — only if at least
        one org needs it.
        """
        admin_memberships_qs = (
            OrganizationUser.objects.filter(
                role__name=BuiltInRole.ORG_ADMIN, role__is_built_in=True
            )
            .select_related("user")
            .order_by("joined_at", "user_id")
        )
        qs = self._list_organizations(is_active=is_active).prefetch_related(
            Prefetch(
                "members",
                queryset=admin_memberships_qs,
                to_attr="_admin_memberships",
            )
        )
        orgs = list(qs)
        fallback_resolved = False
        fallback: list[User] = []
        for org in orgs:
            org.admins = [m.user for m in org._admin_memberships]
            if not org.admins:
                if not fallback_resolved:
                    user = self._get_fallback_admin_user()
                    fallback = [user] if user is not None else []
                    fallback_resolved = True
                org.admins = fallback
        return orgs

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
    def rename_organization(self, org_id: int, name: str) -> Organization:
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

        # Anyone with an already-open WS graph-editing session in this org
        # keeps editing until they reload unless we proactively re-check
        # their permission now. Notify every member so their live sessions
        # disconnect (mirrors UserManagementService.revoke_superadmin, just
        # inverted: many users, one org, instead of one user, many orgs).
        from tables.graph_collab.notifications import GraphEditNotifier

        member_user_ids = list(
            OrganizationUser.objects.filter(org_id=org_id).values_list(
                "user_id", flat=True
            )
        )
        for member_user_id in member_user_ids:
            transaction.on_commit(
                lambda uid=member_user_id: GraphEditNotifier.notify_permission_changed(
                    user_id=uid, org_id=org_id
                )
            )

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
