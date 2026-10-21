"""Deleting for good what a plugin owns in an organization.

Each owned root goes the way a person's delete would take it, then the recycle bin's purge:
a recycle-bin root is binned and purged, a file is binned through storage and purged, and a
root without a bin (a configuration) is hard-deleted. Nothing is left in the recycle bin.
What the organization's own rows lose is what they lose when a person deletes the item: a
link with SET_NULL is cleared (an agent loses its LLM config, a default-model setting is
emptied), and children that cascade go with the root. A delete that would reach another
organization's row is refused (`CascadeOrgGuard`), and that row is kept.

One row per transaction, so a row that fails rolls back alone. A failed row is left alone for
`FAILED_ROW_RETRY_SECONDS`. Users of a resource go before what they use (`owned_purge_order`).

Adding an ownable model: classify it in `ownership_recorder`; a recycle-bin root takes its
place from the bin's `EMPTY_ORDER` by itself, any other model is named in
`EXTRA_PURGE_ORDER`. `test_owned_resource_purger.py` fails until it is.
"""

import time
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum, auto
from functools import cache

from django.apps import apps
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache as shared_cache
from django.db import router, transaction
from django.db.models import Model, Q, QuerySet
from django.db.models.deletion import Collector
from rbac.models import Organization
from tables.models import Graph, Session, StorageFile
from tables.services.cascade_org_guard import CascadeOrgGuard
from tables.services.recycle_bin.deleting import move_to_recycle_bin
from tables.services.recycle_bin.empty_service import EMPTY_ORDER
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.recycle_bin.registry import bin_resources
from tables.services.recycle_bin.sources import RecycleBinSource
from tables.services.storage_service import get_storage_manager
from tables.services.storage_service.recycle_bin import StorageRecycleBinService
from utils.exceptions import CustomAPIExeption
from utils.logger import logger

from plugins.models import PluginGrant, PluginOwnedResource
from plugins.models.grant import MAX_PURGE_ERROR_LENGTH
from plugins.ownership.ownership_recorder import ownable_models

PURGE_ACTOR_TEMPLATE = "plugin {identifier} purge"
FAILED_ROW_RETRY_SECONDS = 3600
FAILED_ROW_CACHE_KEY = "plugins:purge:failed:{pk}"
# Ownable models with no recycle bin, other than files: purged after the files and
# collections and before key-value tables and secrets, configurations before the models they
# use (deleting an LLM model deletes the LLM configs that use it).
EXTRA_PURGE_ORDER: tuple[str, ...] = (
    "tables.LLMConfig",
    "tables.EmbeddingConfig",
    "tables.RealtimeConfig",
    "tables.RealtimeTranscriptionConfig",
    "tables.OpenAIRealtimeConfig",
    "tables.ElevenLabsRealtimeConfig",
    "tables.GeminiRealtimeConfig",
    "tables.LLMModel",
    "tables.EmbeddingModel",
    "tables.RealtimeModel",
    "tables.RealtimeTranscriptionModel",
)
_OPEN_SESSION_STATES = (
    Session.SessionStatus.PENDING,
    Session.SessionStatus.RUN,
    Session.SessionStatus.WAIT_FOR_USER,
)


@cache
def owned_purge_order() -> tuple[type[Model], ...]:
    """Every ownable model, in the order the purger deletes them: the recycle bin's
    `EMPTY_ORDER`, with `EXTRA_PURGE_ORDER` just before key-value tables."""
    resources = bin_resources()
    order: list[type[Model]] = []
    for source in EMPTY_ORDER:
        if source == RecycleBinSource.KEY_VALUE_TABLE:
            order.extend(apps.get_model(label) for label in EXTRA_PURGE_ORDER)
        order.append(StorageFile if source == RecycleBinSource.STORAGE else resources[source].model)
    return tuple(order)


@dataclass(frozen=True)
class PurgePassResult:
    """What one pass did.

    Attributes:
        remaining: Ownership rows still left once the pass ended: rows it did not reach,
            rows another process held, flows with a running session, and failed rows.
        first_error: `"<model> <pk>: <message>"` of the first failed row, at most 2000
            characters; None when no row failed.
    """

    purged: int
    failed: int
    remaining: int
    first_error: str | None


class _Outcome(Enum):
    PURGED = auto()
    WAITING = auto()
    FAILED = auto()
    ORGANIZATION_GONE = auto()


class OwnedResourcePurger:
    def purge(
        self,
        *,
        organization_id: int,
        plugin_identifier: str,
        grant: PluginGrant | None,
        until: float,
    ) -> PurgePassResult:
        """Delete the rows the plugin owns in the organization, in `owned_purge_order()`.

        With `grant`, the rows owned under it and the rows of the organization and plugin
        whose grant is gone; without, only the latter. Stops once `until` (a
        `time.monotonic()` deadline) has passed, after at least one row. Never raises: a row
        that fails, a delete reaching another organization included, is logged, counted and
        left alone for an hour. Stops at once when the organization has been deleted, which
        took everything with it.
        """
        targets = purge_targets(organization_id, plugin_identifier, grant)
        actor = PURGE_ACTOR_TEMPLATE.format(identifier=plugin_identifier)
        purged = failed = 0
        first_error = None
        attempted = 0
        for row_pk in _in_purge_order(targets):
            if attempted and time.monotonic() >= until:
                break
            if shared_cache.get(FAILED_ROW_CACHE_KEY.format(pk=row_pk)) is not None:
                continue
            attempted += 1
            outcome, error = self._purge_row(row_pk, organization_id, plugin_identifier, actor)
            if outcome == _Outcome.ORGANIZATION_GONE:
                break
            if outcome == _Outcome.PURGED:
                purged += 1
            elif outcome == _Outcome.FAILED:
                failed += 1
                first_error = first_error or error
        return PurgePassResult(
            purged=purged, failed=failed, remaining=targets.count(), first_error=first_error
        )

    def _purge_row(
        self, row_pk: int, organization_id: int, identifier: str, actor: str
    ) -> tuple[_Outcome, str | None]:
        model = None
        object_id = None
        try:
            with transaction.atomic():
                # The lock storage writes take first, so a purge never interleaves with an
                # upload, a restore or the organization's deletion.
                if (
                    Organization.objects.select_for_update().filter(pk=organization_id).first()
                    is None
                ):
                    return _Outcome.ORGANIZATION_GONE, None
                row = (
                    PluginOwnedResource.objects.select_for_update(skip_locked=True)
                    .filter(pk=row_pk)
                    .first()
                )
                if row is None:
                    return _Outcome.WAITING, None
                model = ContentType.objects.get_for_id(row.content_type_id).model_class()
                object_id = row.object_id
                if model is None or model not in ownable_models():
                    # A model gone from the code: nothing of it can be run or purged.
                    row.delete()
                    return _Outcome.PURGED, None
                root = _manager(model).select_for_update().filter(pk=object_id).first()
                if root is not None and not _delete_root(root, organization_id, actor):
                    return _Outcome.WAITING, None
                row.delete()
                return _Outcome.PURGED, None
        except Exception as error:  # never raised: one row must not stop the purge of the rest
            shared_cache.set(FAILED_ROW_CACHE_KEY.format(pk=row_pk), 1, FAILED_ROW_RETRY_SECONDS)
            label = model._meta.label if model is not None else "unknown"
            logger.warning(
                "plugins.purge.resource_failed plugin={plugin} org={org} model={model} pk={pk} "
                "error={error}",
                plugin=identifier,
                org=organization_id,
                model=label,
                pk=object_id,
                error=type(error).__name__,
            )
            return _Outcome.FAILED, _error_text(model, object_id, error)


def purge_targets(
    organization_id: int, identifier: str, grant: PluginGrant | None
) -> QuerySet[PluginOwnedResource]:
    """The ownership rows a purge of `grant` deletes: its own and the organization's rows of the
    plugin whose grant is gone; only the latter without a grant."""
    orphaned = Q(org_id=organization_id, plugin_identifier=identifier, grant__isnull=True)
    if grant is None:
        return PluginOwnedResource.objects.filter(orphaned)
    return PluginOwnedResource.objects.filter(Q(grant=grant) | orphaned)


def _in_purge_order(targets: QuerySet[PluginOwnedResource]) -> Iterable[int]:
    """The rows' pks in `owned_purge_order()`, oldest first within a model; one query (content
    types are cached per process). A row of a model outside the order comes last."""
    ranks = {
        ContentType.objects.get_for_model(model).pk: rank
        for rank, model in enumerate(owned_purge_order())
    }
    rows = targets.order_by().values_list("pk", "content_type_id")
    return [pk for pk, _ in sorted(rows, key=lambda row: (ranks.get(row[1], len(ranks)), row[0]))]


def _manager(model: type[Model]):
    """Every row of the model, binned ones included."""
    return getattr(model, "all_objects", None) or model._default_manager


def _delete_root(root: Model, organization_id: int, actor: str) -> bool:
    """Delete `root` (locked) for good; False when it must wait for a later pass."""
    model = type(root)
    if model is StorageFile:
        _purge_file(root, organization_id, actor)
        return True
    if model in {resource.model for resource in bin_resources().values()}:
        if model is Graph and _has_open_session(root):
            return False
        if root.soft_deleted_at is None:
            move_to_recycle_bin(root, None)
        binned = model.deleted_objects.select_for_update().get(pk=root.pk)
        PurgeService.purge(binned, actor=actor)
        return True
    _hard_delete(root, actor)
    return True


def _has_open_session(graph: Graph) -> bool:
    return Session.objects.filter(graph_id=graph.pk, status__in=_OPEN_SESSION_STATES).exists()


def _purge_file(file: StorageFile, organization_id: int, actor: str) -> None:
    """Bin a live file through storage, then purge it from the bin.

    A file binned together with its folder is not an entry of the bin on its own, and the
    folder is the organization's: only the file's row and its trashed object are deleted.
    """
    manager = get_storage_manager()
    if file.soft_deleted_at is None:
        manager.delete(organization_id, file.path, user=None)
        file = StorageFile.all_objects.select_for_update().get(pk=file.pk)
    bin_service = StorageRecycleBinService(manager)
    if StorageRecycleBinService.top_level(organization_id).filter(pk=file.pk).exists():
        bin_service.purge(organization_id, file.pk, actor=actor)
        return
    using = router.db_for_write(StorageFile)
    rows = StorageFile.all_objects.using(using).filter(pk=file.pk)
    collector = Collector(using=using, origin=rows)
    collector.collect(rows)
    CascadeOrgGuard(organization_id, f"storage entry {file.pk}", using).check_collected(collector)
    collector.delete()
    manager.delete_trash_path(organization_id, file.soft_delete_batch, file.path)
    logger.info(
        "Purged storage file {pk} of org {org_id} (batch {batch}) by {actor}",
        pk=file.pk,
        org_id=organization_id,
        batch=file.soft_delete_batch,
        actor=actor,
    )


def _hard_delete(root: Model, actor: str) -> None:
    """Delete a root that has no recycle bin, refused when its cascade reaches another
    organization's row."""
    using = router.db_for_write(type(root))
    collector = Collector(using=using, origin=root)
    collector.collect([root])
    CascadeOrgGuard.for_root(root, using).check_collected(collector)
    pk = root.pk
    organization_id = root.org_id
    collector.delete()
    logger.info(
        "Purged {model} {pk} of org {org_id} by {actor}",
        model=type(root).__name__,
        pk=pk,
        org_id=organization_id,
        actor=actor,
    )


def _error_text(model: type[Model] | None, object_id: int | None, error: Exception) -> str:
    """What the SuperAdmin reads about a failed row. Only EpicStaff's own errors keep their
    message, which never names another organization's data; any other error is named by its
    class alone, as in the log."""
    name = model._meta.verbose_name.capitalize() if model is not None else "Resource"
    message = str(error.detail) if isinstance(error, CustomAPIExeption) else type(error).__name__
    return f"{name} {object_id}: {message}"[:MAX_PURGE_ERROR_LENGTH]
