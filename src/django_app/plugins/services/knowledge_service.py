"""Knowledge indexing of installed plugins, and the plugin state it drives.

There is no background worker: indexing is started right after install or retry,
and a preparing plugin's state is computed from its collections' indexing status
whenever the plugin is read.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from src.shared.enums.knowledge_new import RAGStrategy
from tables.clients import KnowledgeClient
from tables.models import SourceCollection
from tables.models.knowledge_models import NaiveRag, NaiveRagDocumentConfig
from tables.services.knowledge_services.indexing_service import IndexingService
from tables.services.knowledge_services.naive_rag_service import NaiveRagService
from tables.services.secrets import SecretResolver
from utils.logger import logger

from plugins.exceptions import PluginNotRetryableError, PluginSuspendedError
from plugins.models import Plugin, PluginResource
from plugins.resource_types import PluginResourceType

_RagStatus = NaiveRag.NaiveRagStatus
_FAILED_STATUSES = frozenset({_RagStatus.FAILED, _RagStatus.CANCELLED, _RagStatus.PARTIAL})
_MAX_REASON_DETAIL = 300


@dataclass(frozen=True)
class KnowledgeStatus:
    """Indexing status of one knowledge entry of a plugin.

    `rag_status` is None when the collection, its naive RAG or its registry row
    is gone.
    """

    name: str
    rag_status: str | None


def plugin_state_from_knowledge(entries: list[KnowledgeStatus]) -> tuple[str, str]:
    """Map a plugin's knowledge indexing statuses to its `(state, status_reason)`.

    Any missing, failed, cancelled, partially indexed or outdated entry makes the
    plugin need attention, named after the first such entry. Only when every
    entry finished indexing is the plugin ready; otherwise it is still preparing.
    """
    for entry in entries:
        if entry.rag_status is None:
            return Plugin.State.NEEDS_ATTENTION, f"Knowledge '{entry.name}' was deleted."
        if entry.rag_status in _FAILED_STATUSES:
            return Plugin.State.NEEDS_ATTENTION, f"Knowledge '{entry.name}' failed to index."
        if entry.rag_status == _RagStatus.OUTDATED:
            return (
                Plugin.State.NEEDS_ATTENTION,
                f"Knowledge '{entry.name}' is out of date and must be indexed again.",
            )
    if all(entry.rag_status == _RagStatus.COMPLETED for entry in entries):
        return Plugin.State.READY, ""
    return Plugin.State.PREPARING, ""


@dataclass(frozen=True)
class _Knowledge:
    name: str
    collection_id: int | None
    naive_rag_id: int | None
    rag_status: str | None


def _knowledge_by_plugin(plugins: list[Plugin]) -> dict[int, list[_Knowledge]]:
    """Every knowledge entry the plugins' manifests declare, resolved to live rows.

    Three queries for the whole batch, whatever its size.
    """
    collection_by_ref: dict[tuple[int, str], int] = {
        (plugin_id, ref): object_id
        for plugin_id, ref, object_id in PluginResource.objects.filter(
            plugin__in=plugins, resource_type=PluginResourceType.SOURCE_COLLECTION
        ).values_list("plugin_id", "manifest_ref", "object_id")
    }
    existing = set(
        SourceCollection.objects.filter(collection_id__in=collection_by_ref.values()).values_list(
            "collection_id", flat=True
        )
    )
    rag_by_collection = {
        collection_id: (naive_rag_id, rag_status)
        for collection_id, naive_rag_id, rag_status in NaiveRag.objects.filter(
            base_rag_type__source_collection_id__in=existing
        ).values_list("base_rag_type__source_collection_id", "naive_rag_id", "rag_status")
    }

    result: dict[int, list[_Knowledge]] = {}
    for plugin in plugins:
        entries = []
        for declared in plugin.manifest.get("knowledge", []):
            collection_id = collection_by_ref.get((plugin.pk, declared["name"]))
            if collection_id not in existing:
                collection_id = None
            naive_rag_id, rag_status = rag_by_collection.get(collection_id, (None, None))
            entries.append(_Knowledge(declared["name"], collection_id, naive_rag_id, rag_status))
        result[plugin.pk] = entries
    return result


def refresh_states(plugins: list[Plugin]) -> None:
    """Settle preparing plugins into ready or needs_attention from their indexing status.

    Updates the given instances in place and persists a change. A plugin that is
    not preparing is left alone: only a retry sends it back to preparing.
    """
    preparing = [plugin for plugin in plugins if plugin.state == Plugin.State.PREPARING]
    if not preparing:
        return
    knowledge = _knowledge_by_plugin(preparing)
    for plugin in preparing:
        state, reason = plugin_state_from_knowledge(
            [KnowledgeStatus(entry.name, entry.rag_status) for entry in knowledge[plugin.pk]]
        )
        if state == plugin.state:
            continue
        now = timezone.now()
        # Conditional, so a reader never overwrites a state another request already settled.
        Plugin.objects.filter(pk=plugin.pk, state=Plugin.State.PREPARING).update(
            state=state, status_reason=reason, updated_at=now
        )
        plugin.state, plugin.status_reason, plugin.updated_at = state, reason, now


def start_indexing(plugin_pk: int, *, only_unfinished: bool = False) -> None:
    """Start indexing a plugin's knowledge collections in the knowledge service.

    Runs outside any transaction, after install or retry committed. Indexing then
    proceeds in the knowledge service; `refresh_states` reads the outcome. If a
    collection cannot even be started, the plugin needs attention with the reason.

    Args:
        only_unfinished: Skip collections that already finished indexing (retry).
    """
    plugin = Plugin.objects.filter(pk=plugin_pk).first()
    if plugin is None:
        return
    for entry in _knowledge_by_plugin([plugin])[plugin.pk]:
        if entry.naive_rag_id is None:
            # refresh_states reports the missing collection; nothing to start.
            continue
        if only_unfinished and entry.rag_status == _RagStatus.COMPLETED:
            continue
        # Broad on purpose: this runs after the response's transaction committed,
        # so an escaping error would turn a finished install into a 500. Every
        # failure (validation, secret, knowledge service) becomes a visible state.
        try:
            _index(entry.naive_rag_id, org_id=plugin.org_id, name=entry.name)
        except Exception as exc:
            logger.exception("Plugin {} could not start indexing '{}'", plugin.pk, entry.name)
            _mark_needs_attention(
                plugin.pk, f"Knowledge '{entry.name}' could not start indexing: {_detail(exc)}"
            )
            return


def retry(plugin: Plugin) -> None:
    """Start indexing again every knowledge collection of the plugin that did not finish.

    Documents added to a collection since install get default document configs
    first, so they are indexed too.

    Raises:
        PluginSuspendedError: the plugin is suspended.
        PluginNotRetryableError: the plugin does not need attention.
    """
    refresh_states([plugin])
    if plugin.suspended:
        raise PluginSuspendedError(plugin.name)
    if plugin.state != Plugin.State.NEEDS_ATTENTION:
        raise PluginNotRetryableError()
    with transaction.atomic():
        unfinished = []
        for entry in _knowledge_by_plugin([plugin])[plugin.pk]:
            if entry.naive_rag_id is None:
                continue
            NaiveRagService.init_document_configs(entry.naive_rag_id)
            if entry.rag_status != _RagStatus.COMPLETED:
                unfinished.append(entry.naive_rag_id)
        # The knowledge service answers before it marks a RAG processing, so the
        # old failure would still be on the row when the plugin is next read and
        # would undo this retry. It recomputes the status when its run finishes.
        NaiveRag.objects.filter(pk__in=unfinished).update(
            rag_status=_RagStatus.NEW, error_message=None
        )
        Plugin.objects.filter(pk=plugin.pk).update(
            state=Plugin.State.PREPARING, status_reason="", updated_at=timezone.now()
        )
    start_indexing(plugin.pk, only_unfinished=True)
    plugin.refresh_from_db()


def _index(naive_rag_id: int, *, org_id: int, name: str) -> None:
    """Start one naive RAG's indexing the way ProcessRagIndexingView does."""
    indexing_data = IndexingService.validate_and_prepare_indexing(naive_rag_id, RAGStrategy.NAIVE)
    embedding_api_key = SecretResolver().resolve(
        secret_id=indexing_data["embedder_api_key_secret_id"],
        org_id=org_id,
        context=f"plugin knowledge '{name}'",
    )
    document_ids = frozenset(
        NaiveRagDocumentConfig.objects.filter(naive_rag_id=naive_rag_id).values_list(
            "pk", flat=True
        )
    )
    with KnowledgeClient() as client:
        client.index(
            strategy=RAGStrategy.NAIVE,
            rag_id=naive_rag_id,
            document_ids=document_ids,
            embedding_api_key=embedding_api_key,
            llm_api_key=None,
        )


def _mark_needs_attention(plugin_pk: int, reason: str) -> None:
    Plugin.objects.filter(pk=plugin_pk).update(
        state=Plugin.State.NEEDS_ATTENTION, status_reason=reason, updated_at=timezone.now()
    )


def _detail(exc: Exception) -> str:
    detail = str(getattr(exc, "detail", None) or exc) or exc.__class__.__name__
    return detail if len(detail) <= _MAX_REASON_DETAIL else detail[:_MAX_REASON_DETAIL] + "…"
