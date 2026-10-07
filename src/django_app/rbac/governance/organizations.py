from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, QuerySet
from loguru import logger
from storage_credentials.exceptions import OrgStorageProvisioningError
from storage_credentials.services.org_provisioning_service import (
    org_storage_provisioning_service,
)
from tables.models.user import User

from rbac.exceptions import (
    DefaultOrganizationNotDeletableError,
    LastActiveOrganizationError,
    LastOrganizationError,
    OrganizationNameConflictError,
    OrganizationNotFoundError,
)
from rbac.governance.cross_org_base import CrossOrgResourceService
from rbac.governance.delete_collector import (
    ModelCount,
    build_affected_resources,
    build_collector,
    summarize,
)
from rbac.governance.delete_verification import assert_delete_phrase
from rbac.governance.organization_deletion import (
    OrganizationDeletionCounts,
    participants,
)
from rbac.models import Organization, OrganizationConfig, OrganizationUser
from rbac.models.enums import BuiltInRole, Permission, ResourceType


@dataclass
class OrganizationDeleteReport:
    """What deleting an organization removed, or would remove."""

    organization_id: int
    affected_resources: dict[str, int] = field(default_factory=dict)


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
        ORGANIZATIONS.READ in that org (or superadmin); an org the caller
        cannot see — not a member, or a member without that bit — surfaces as
        OrganizationNotFoundError (404 — no existence leak). `assert_can` is
        redundant for this action, since visibility already implies READ, and
        is kept so every method on this service reads as the same
        visibility-then-verb sequence."""
        effective = self.resolve_for_write(actor, org_id, action=Permission.READ)
        self.assert_can(effective, Permission.READ)
        return self._get_organization_with_member_count(org_id)

    def _list_organizations(self, is_active: bool | None = None) -> QuerySet[Organization]:
        qs = (
            Organization.objects.annotate(member_count=Count("members"))
            .select_related("config")
            .order_by("-is_active", "name")
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
        org_storage_provisioning_service.provision_for_organization(org)
        OrganizationConfig.objects.create(org=org)
        return self._get_organization_with_member_count(org.pk)

    @transaction.atomic
    def rename_organization(self, actor, org_id: int, name: str) -> Organization:
        effective = self.resolve_for_write(actor, org_id, action=Permission.UPDATE)
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
    def update_audit_retention(self, org_id: int, audit_retention_days: int) -> Organization:
        """Lives on OrganizationConfig, not Organization itself. get_or_create
        is defensive insurance only - every org should already have a config
        row from create_organization (or the migration backfill, for
        pre-existing orgs)."""
        org = self._get_locked_org(org_id)
        config, _ = OrganizationConfig.objects.select_for_update().get_or_create(org=org)
        if config.audit_retention_days != audit_retention_days:
            config.audit_retention_days = audit_retention_days
            config.save(update_fields=["audit_retention_days"])
        return self._get_organization_with_member_count(org.pk)

    @transaction.atomic
    def deactivate_organization(self, org_id: int) -> Organization:
        org = self._get_locked_org(org_id)
        if not org.is_active:
            return self._get_organization_with_member_count(org.pk)
        self._assert_can_deactivate()
        org.is_active = False
        org.save(update_fields=["is_active", "updated_at"])
        # `is_active` must reflect the caller's intent regardless of MinIO's
        # availability -- an org that should be deactivated (a
        # security-relevant action) must not stay active just because MinIO
        # is unreachable. The failure is logged, not silently swallowed, so
        # the leftover MinIO user can be reconciled out of band.
        self._deprovision_storage(org.id, "during deactivation")
        return self._get_organization_with_member_count(org.pk)

    @staticmethod
    def _deprovision_storage(org_id: int, occasion: str) -> None:
        try:
            org_storage_provisioning_service.deprovision_for_organization(org_id)
        except OrgStorageProvisioningError as error:
            logger.error(
                "Failed to deprovision MinIO storage for org_id={} {}; "
                "the MinIO user was left in place and needs out-of-band "
                "reconciliation: {}",
                org_id,
                occasion,
                error,
            )

    @staticmethod
    def _assert_can_deactivate() -> None:
        """Refuses if this would leave zero active organizations. Locks the
        full set of active orgs (not just the target row) so two concurrent
        deactivate calls cannot both drive the active count to zero."""
        active_orgs = Organization.objects.filter(is_active=True).select_for_update()
        if len(active_orgs) <= 1:
            raise LastActiveOrganizationError()

    @transaction.atomic
    def reactivate_organization(self, org_id: int) -> Organization:
        org = self._get_locked_org(org_id)
        if org.is_active:
            return self._get_organization_with_member_count(org.pk)
        org.is_active = True
        org.save(update_fields=["is_active", "updated_at"])
        # Same reasoning as deactivate_organization(): is_active always
        # commits regardless of MinIO's availability.
        try:
            org_storage_provisioning_service.provision_for_organization(org)
        except OrgStorageProvisioningError as error:
            logger.error(
                "Failed to provision MinIO storage for org_id={} during "
                "reactivation; org.is_active is True regardless -- storage "
                "for this org needs out-of-band provisioning: {}",
                org.id,
                error,
            )
        return self._get_organization_with_member_count(org.pk)

    # ---- deletion ----

    def _target_org_or_404(self, org_id: int) -> Organization:
        """Fetch the organization a delete/preview targets, or raise OrganizationNotFoundError."""
        try:
            return Organization.objects.get(pk=org_id)
        except Organization.DoesNotExist as exc:
            raise OrganizationNotFoundError() from exc

    @staticmethod
    def _assert_deletable_org(instance: Organization) -> None:
        """Refuse the default organization and the last remaining active one."""
        if instance.is_default:
            raise DefaultOrganizationNotDeletableError()
        if not Organization.objects.filter(is_active=True).exclude(pk=instance.pk).exists():
            raise LastOrganizationError()

    def preview_delete(self, actor: User, org_id: int) -> OrganizationDeleteReport:
        """Report what deleting an organization would remove, without deleting anything."""
        instance = self._target_org_or_404(org_id)
        self._assert_deletable_org(instance)

        registered = participants()
        participant_counts = [participant.count(instance) for participant in registered]
        external_counts = [
            participant.count_external_artifacts(instance) for participant in registered
        ]
        affected = self._affected_resources(
            summarize(build_collector(instance)), participant_counts, external_counts
        )
        payload = OrganizationDeleteReport(organization_id=instance.pk, affected_resources=affected)
        logger.info(
            "OrganizationManagementService.preview_delete actor={actor} target={target} resources={resources}",
            actor=getattr(actor, "email", "system"),
            target=instance.name,
            resources=affected,
        )
        return payload

    @transaction.atomic
    def delete_organization(
        self, actor: User, org_id: int, *, verification_phrase: str | None
    ) -> OrganizationDeleteReport:
        """Permanently delete an organization and everything it owns, refusing the default organization and the last remaining active one.

        `verification_phrase` must be exactly `delete-<organization name>`, compared against the unlocked read of the organization before external I/O or any lock.

        Also deprovisions the org's MinIO/RustFS storage IAM user, same as
        `deactivate_organization()` -- queued onto the same post-commit
        `cleanups` list as the other participants' sweeps, so it runs after
        the delete has actually committed and is failure-tolerant (a storage
        error is logged, never rolls back or blocks the delete).
        """
        instance = self._target_org_or_404(org_id)
        self._assert_deletable_org(instance)
        assert_delete_phrase(verification_phrase, instance.name)

        registered = participants()
        # External artifact counts may do network I/O (a MinIO listing); they
        # run before any lock is taken, so they never extend how long the
        # locks taken below are held. They do run inside this method's own
        # @transaction.atomic, so a DB connection is held open across that
        # unbounded network call.
        external_counts = [
            participant.count_external_artifacts(instance) for participant in registered
        ]

        locked = {
            org.pk: org
            for org in Organization.objects.filter(is_active=True)
            .order_by("pk")
            .select_for_update()
        }
        # `instance.is_default` is read unlocked here rather than from
        # `locked` (which only holds active orgs, and could miss an inactive
        # target): safe because `is_default` has no live write path -- it is
        # set once, by SuperadminBootstrap at provisioning time, and never
        # toggled by request-handling code.
        if instance.is_default:
            raise DefaultOrganizationNotDeletableError()
        # Narrower, lock-scoped re-check of the same last-active-org invariant `_assert_deletable_org` enforces unlocked above -- not a full re-implementation, so don't assume edits to one mirror the other.
        if instance.pk in locked and not set(locked) - {instance.pk}:
            raise LastOrganizationError()

        # Each participant counts non-destructively immediately before its
        # sweep, under the same locks, so this agrees with the preview. The
        # sweeps run before build_collector: the rows they remove must already
        # be gone when the collector walks the organization's relations.
        participant_counts: list[OrganizationDeletionCounts] = []
        cleanups = []
        for participant in registered:
            participant_counts.append(participant.count(instance))
            cleanups.append(participant.sweep(instance))
        # Snapshot the id before `collector.delete()` below: Django's
        # Collector nulls out the PK on every instance it collected
        organization_id = instance.pk
        cleanups.append(lambda: self._deprovision_storage(organization_id, "after deletion"))
        collector = build_collector(instance)
        affected = self._affected_resources(
            summarize(collector), participant_counts, external_counts
        )
        payload = OrganizationDeleteReport(organization_id=instance.pk, affected_resources=affected)
        collector.delete()
        for cleanup in cleanups:
            if cleanup is not None:
                # robust: a failing cleanup is logged and never undoes the
                # committed delete or skips another participant's cleanup.
                transaction.on_commit(cleanup, robust=True)

        logger.info(
            "OrganizationManagementService.delete_organization actor={actor} target={target} resources={resources}",
            actor=getattr(actor, "email", "system"),
            target=instance.name,
            resources=affected,
        )
        return payload

    @staticmethod
    def _affected_resources(
        collector_by_model: list[ModelCount],
        participant_counts: list[OrganizationDeletionCounts],
        external_counts: list[dict[str, int]],
    ) -> dict[str, int]:
        """Fold the collector's rows, each participant's swept rows and every external artifact count into the delete report."""
        swept_by_model = [row for counts in participant_counts for row in counts.by_model]
        external_totals: dict[str, int] = {}
        for counts in [
            *external_counts,
            *(counts.external_counts for counts in participant_counts),
        ]:
            for name, count in counts.items():
                external_totals[name] = external_totals.get(name, 0) + count
        return build_affected_resources(
            OrganizationManagementService._merge_sweep_counts(collector_by_model, swept_by_model),
            external_totals,
        )

    @staticmethod
    def _merge_sweep_counts(
        collector_by_model: list[ModelCount], sweep_counts: list[ModelCount]
    ) -> list[ModelCount]:
        """Replace the collector's own count for every swept model with the sweep's own count, so dry-run and real mode always agree."""
        swept_labels = {row.model for row in sweep_counts}
        kept = [row for row in collector_by_model if row.model not in swept_labels]
        return kept + sweep_counts

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
