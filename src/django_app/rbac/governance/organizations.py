from dataclasses import dataclass, field

from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.db.models import Count, Prefetch, Q, QuerySet
from loguru import logger
from tables.models.base_models import DefaultBaseModel
from tables.models.crew_models import Task, TemplateAgent
from tables.models.knowledge_models.collection_models import (
    DocumentContent,
    DocumentMetadata,
    SourceCollection,
)
from tables.models.realtime_models import ConversationRecording, RealtimeAgentChat
from tables.models.user import User
from tables.services.storage_service import get_storage_backend

from rbac.access.delete_collector import (
    ModelCount,
    build_affected_resources,
    build_collector,
    summarize,
)
from rbac.exceptions import (
    DefaultOrganizationNotDeletableError,
    LastActiveOrganizationError,
    LastOrganizationError,
    OrganizationNameConflictError,
    OrganizationNotFoundError,
)
from rbac.governance.cross_org_base import CrossOrgResourceService
from rbac.models import Organization, OrganizationUser
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
    def deactivate_organization(self, org_id: int) -> Organization:
        orgs = Organization.objects.filter(is_active=True).order_by("pk").select_for_update()
        orgs_map = {o.pk: o for o in orgs}
        if org_id in orgs_map:
            if len(orgs_map) <= 1:
                raise LastActiveOrganizationError()
            target = orgs_map[org_id]
        else:
            target = self._get_locked_org(org_id)

        if target.is_active:
            target.is_active = False
            target.save(update_fields=["is_active", "updated_at"])

        return self._get_organization_with_member_count(target.pk)

    @transaction.atomic
    def reactivate_organization(self, org_id: int) -> Organization:
        org = self._get_locked_org(org_id)
        if org.is_active:
            return self._get_organization_with_member_count(org.pk)
        org.is_active = True
        org.save(update_fields=["is_active", "updated_at"])
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

        sweep_counts, recording_count = self._count_org_delete_sweep(instance)
        by_model = self._merge_sweep_counts(summarize(build_collector(instance)), sweep_counts)
        storage_count = self._org_external_artifacts(instance)  # int | None
        external_counts = {
            "storage_files": (storage_count or 0) + recording_count,
        }
        affected = build_affected_resources(by_model, external_counts)
        payload = OrganizationDeleteReport(organization_id=instance.pk, affected_resources=affected)
        logger.info(
            "OrganizationManagementService.preview_delete actor={actor} target={target} resources={resources}",
            actor=getattr(actor, "email", "system"),
            target=instance.name,
            resources=affected,
        )
        return payload

    @transaction.atomic
    def delete_organization(self, actor: User, org_id: int) -> OrganizationDeleteReport:
        """Permanently delete an organization and everything it owns, refusing the default organization and the last remaining active one."""
        instance = self._target_org_or_404(org_id)
        self._assert_deletable_org(instance)

        # external_artifacts does network I/O (a MinIO listing); it runs
        # before any lock is taken, so it never extends how long the locks
        # taken below are held. It does run inside this method's own
        # @transaction.atomic, so a DB connection is held open across that
        # unbounded network call -- no lock is held at this point, so this
        # doesn't extend lock hold time.
        storage_count = self._org_external_artifacts(instance)  # int | None
        # Captured before the delete: after it, the row these read from is gone.
        snapshot = {"storage_prefix": self._org_storage_prefix(instance)}

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

        # Counted non-destructively, immediately before the sweep runs (same
        # locked state the sweep itself acts on), so this agrees with the
        # preview for the same target -- see _merge_sweep_counts. The sweep
        # itself still runs before build_collector, exactly as before: the
        # rows it removes must already be gone by the time the collector
        # walks the organization's remaining relations.
        sweep_counts, recording_count = self._count_org_delete_sweep(instance)
        snapshot["recording_files"] = self._perform_org_delete_sweep(instance)
        collector = build_collector(instance)
        by_model = self._merge_sweep_counts(summarize(collector), sweep_counts)
        external_counts = {
            "storage_files": (storage_count or 0) + recording_count,
        }
        affected = build_affected_resources(by_model, external_counts)
        payload = OrganizationDeleteReport(organization_id=instance.pk, affected_resources=affected)
        collector.delete()
        transaction.on_commit(lambda: self._cleanup_org_delete_external(snapshot))

        logger.info(
            "OrganizationManagementService.delete_organization actor={actor} target={target} resources={resources}",
            actor=getattr(actor, "email", "system"),
            target=instance.name,
            resources=affected,
        )
        return payload

    @staticmethod
    def _org_storage_prefix(instance: Organization) -> str:
        """Return the MinIO key prefix owning this organization's objects."""
        return f"org_{instance.pk}/"

    def _org_external_artifacts(self, instance: Organization) -> int | None:
        """Count the MinIO objects this delete would orphan, degrading to None on a storage failure."""
        prefix = self._org_storage_prefix(instance)
        try:
            backend = get_storage_backend(organization_prefix=prefix)
            objects = backend.list_all_objects("")
        except Exception as exc:
            logger.warning(
                "OrganizationManagementService.delete_organization storage_preview_failed org_id={org_id} error={error}",
                org_id=instance.pk,
                error=exc,
            )
            return None
        return len(objects)

    @staticmethod
    def _org_delete_sweep_querysets(instance: Organization) -> dict[str, QuerySet]:
        """Return the querysets the org-delete sweep enumerates and removes.

        Computed the same way for the count-only preview (both dry-run and
        real mode) and the real sweep, so the two can never disagree. Uses
        `SourceCollection.all_objects` (not the soft-delete-filtered
        `.objects`) so a collection already soft-deleted before this org
        delete started is still swept, instead of surviving with its
        `DocumentContent` orphaned.
        """
        return {
            "collections": SourceCollection.all_objects.filter(org=instance),
            "tasks": Task.objects.filter(Q(crew__org=instance) | Q(agent__org=instance)),
            "template_agents": TemplateAgent.objects.filter(
                Q(llm_config__org=instance) | Q(fcm_llm_config__org=instance)
            ),
            "rt_chats": RealtimeAgentChat.objects.filter(
                Q(openai_config__org=instance)
                | Q(elevenlabs_config__org=instance)
                | Q(gemini_config__org=instance)
            ),
        }

    @staticmethod
    def _count_org_delete_sweep(instance: Organization) -> tuple[list[ModelCount], int]:
        """Count what `_perform_org_delete_sweep` would remove, without deleting anything.

        Run in both dry-run and real mode so the reported counts can never
        disagree -- see `_merge_sweep_counts`. Returns the per-model counts
        and the number of `ConversationRecording` audio files that would be
        orphaned.
        """
        targets = OrganizationManagementService._org_delete_sweep_querysets(instance)

        counts: list[ModelCount] = []
        for model, qs in (
            (Task, targets["tasks"]),
            (TemplateAgent, targets["template_agents"]),
            (RealtimeAgentChat, targets["rt_chats"]),
        ):
            count = qs.count()
            if count:
                counts.append(ModelCount(model=model._meta.label, count=count))

        collection_ids = list(targets["collections"].values_list("pk", flat=True))
        if collection_ids:
            counts.append(ModelCount(model=SourceCollection._meta.label, count=len(collection_ids)))

        doc_qs = DocumentMetadata.all_objects.filter(source_collection_id__in=collection_ids)
        doc_count = doc_qs.count()
        if doc_count:
            counts.append(ModelCount(model=DocumentMetadata._meta.label, count=doc_count))

        # Predict which DocumentContent rows would become unreferenced once
        # the sweep removes this org's own DocumentMetadata -- excluding, not
        # yet deleting, those rows, since this method must not touch the DB.
        content_ids = list(
            doc_qs.exclude(document_content__isnull=True)
            .values_list("document_content_id", flat=True)
            .distinct()
        )
        unreferenced_count = 0
        if content_ids:
            referenced_elsewhere = set(
                DocumentMetadata.all_objects.filter(document_content_id__in=content_ids)
                .exclude(source_collection_id__in=collection_ids)
                .values_list("document_content_id", flat=True)
                .distinct()
            )
            unreferenced_count = len(set(content_ids) - referenced_elsewhere)
        if unreferenced_count:
            counts.append(ModelCount(model=DocumentContent._meta.label, count=unreferenced_count))

        recording_count = ConversationRecording.objects.filter(
            rt_agent_chat__in=targets["rt_chats"]
        ).count()
        if recording_count:
            counts.append(
                ModelCount(model=ConversationRecording._meta.label, count=recording_count)
            )

        return counts, recording_count

    @staticmethod
    def _merge_sweep_counts(
        collector_by_model: list[ModelCount], sweep_counts: list[ModelCount]
    ) -> list[ModelCount]:
        """Replace the collector's own count for every swept model with the sweep's own count, so dry-run and real mode always agree."""
        swept_labels = {row.model for row in sweep_counts}
        kept = [row for row in collector_by_model if row.model not in swept_labels]
        return kept + sweep_counts

    @staticmethod
    def _perform_org_delete_sweep(instance: Organization) -> list[str]:
        """Hard-delete the knowledge collections, their now-unreferenced content, and the deprecated org-linked rows the Collector's own cascade would otherwise leave behind (nulled FKs) or miss entirely.

        Runs regardless of `settings.SOFT_DELETE`: an organization's own
        permanent delete must not leave its knowledge content behind under
        the platform's soft-delete default, and a bulk `QuerySet.delete()`
        bypasses `SoftDeleteMixin.delete()` by design, which is exactly the
        hard delete wanted here. Returns the storage names of the
        `ConversationRecording` audio files this removes, for the caller to
        purge from storage after the transaction commits.
        """
        targets = OrganizationManagementService._org_delete_sweep_querysets(instance)

        recording_files = list(
            ConversationRecording.objects.filter(rt_agent_chat__in=targets["rt_chats"]).values_list(
                "file", flat=True
            )
        )

        collection_ids = list(targets["collections"].values_list("pk", flat=True))
        content_ids = list(
            DocumentMetadata.all_objects.filter(source_collection_id__in=collection_ids)
            .exclude(document_content__isnull=True)
            .values_list("document_content_id", flat=True)
            .distinct()
        )

        targets["collections"].delete()

        if content_ids:
            DocumentContent.objects.filter(id__in=content_ids).annotate(
                ref_count=Count("metadata_records")
            ).filter(ref_count=0).delete()

        targets["tasks"].delete()
        targets["template_agents"].delete()
        targets["rt_chats"].delete()

        return [name for name in recording_files if name]

    @staticmethod
    def _cleanup_org_delete_external(snapshot: dict) -> None:
        """Reset the platform default cache and purge every MinIO object under the organization's prefix and every swept ConversationRecording audio file, logging rather than raising on failure."""
        try:
            # The cascade nulls Default* singleton FKs with a raw UPDATE, which
            # the process-level cache in DefaultBaseModel.save() never sees.
            DefaultBaseModel._load_cache.clear()
            backend = get_storage_backend(organization_prefix=snapshot["storage_prefix"])
            backend.delete_prefix("")
        except Exception as exc:
            logger.error(
                "OrganizationManagementService.delete_organization cleanup failed error={error}",
                error=exc,
            )
        for name in snapshot.get("recording_files", []):
            try:
                default_storage.delete(name)
            except Exception as exc:
                logger.error(
                    "OrganizationManagementService.delete_organization recording_cleanup_failed name={name} error={error}",
                    name=name,
                    error=exc,
                )

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
