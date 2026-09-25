from django.core.files.storage import default_storage
from django.db.models import Count, Q, QuerySet
from loguru import logger
from rbac.access.delete_collector import ModelCount
from rbac.governance.organization_deletion import OrganizationDeletionCounts, PostCommitCleanup
from rbac.models import Organization
from tables.models.base_models import DefaultBaseModel
from tables.models.crew_models import Task, TemplateAgent
from tables.models.knowledge_models.collection_models import (
    DocumentContent,
    DocumentMetadata,
    SourceCollection,
)
from tables.models.realtime_models import ConversationRecording, RealtimeAgentChat
from tables.services.storage_service import get_storage_backend
from tables.services.storage_service.manager import StorageManager

STORAGE_FILES = "storage_files"

TABLES_RESOURCE_NAMES: dict[str, str] = {
    # user cascade
    "tables.PythonCodeToolFavorite": "tool_favorites",
    "tables.McpToolFavorite": "tool_favorites",
    "tables.FlowAssistantConversation": "assistant_conversations",
    "tables.FlowAssistantMessage": "assistant_conversations",
    # org cascade -- direct
    "tables.Graph": "flow",
    "tables.Session": "sessions",
    "tables.Agent": "agents",
    "tables.Crew": "crews",
    "tables.Secret": "secrets",
    "tables.Label": "labels",
    "tables.WebhookTrigger": "webhook_triggers",
    "tables.LLMModel": "llm_models",
    "tables.LLMConfig": "llm_configs",
    "tables.EmbeddingModel": "embedding_models",
    "tables.EmbeddingConfig": "embedding_configs",
    "tables.PythonCodeTool": "tools",
    "tables.McpTool": "tools",
    "tables.RealtimeModel": "realtime_configs",
    "tables.RealtimeConfig": "realtime_configs",
    "tables.RealtimeTranscriptionModel": "realtime_configs",
    "tables.RealtimeTranscriptionConfig": "realtime_configs",
    "tables.OpenAIRealtimeConfig": "realtime_configs",
    "tables.ElevenLabsRealtimeConfig": "realtime_configs",
    "tables.GeminiRealtimeConfig": "realtime_configs",
    "tables.RealtimeSessionItem": "realtime_configs",
    "tables.SourceCollection": "knowledge_collections",
    "tables.DocumentMetadata": "knowledge_documents",
    "tables.DocumentContent": "knowledge_documents",
    "agents.AgentDefinition": "agent_definitions",
    "agents.Surface": "surfaces",
    "tables.RealtimeChannel": "realtime_channels",
    # org cascade -- swept (deprecated, SET_NULL-only reachable, removed by
    # TablesOrganizationDeletion.sweep, not the Collector)
    "tables.Task": "tasks",
    "tables.TemplateAgent": "template_agents",
    "tables.RealtimeAgentChat": "realtime_agent_chats",
}

# Deliberately excluded: graph-internal structure (implied by "flow"), tool
# sub-detail (implied by "tools"), and DB bookkeeping for files already
# counted via the "storage_files" external artifact. Listed so the
# coverage-guard tests can tell "known, meant to be silent" apart from
# "nobody mapped this yet".
TABLES_EXCLUDED_RESOURCE_LABELS: frozenset[str] = frozenset(
    {
        "tables.StartNode",
        "tables.EndNode",
        "tables.CrewNode",
        "tables.PythonNode",
        "tables.KnowledgeNode",
        "tables.FileExtractorNode",
        "tables.AudioTranscriptionNode",
        "tables.SubGraphNode",
        "tables.DecisionTableNode",
        "tables.WebhookTriggerNode",
        "tables.TelegramTriggerNode",
        "tables.ScheduleTriggerNode",
        "tables.ClassificationDecisionTableNode",
        "tables.TaskNode",
        "tables.AgentNode",
        "tables.Edge",
        "tables.ConditionalEdge",
        "tables.GraphOrganization",
        "tables.GraphOrganizationUser",
        "tables.GraphNote",
        "tables.GraphVersion",
        "tables.GraphStorageFile",
        "tables.AgentNodeTask",
        "tables.ConditionGroup",
        "tables.Condition",
        "tables.ClassificationDecisionTablePrompt",
        "tables.ClassificationConditionGroup",
        "tables.TelegramTriggerNodeField",
        "tables.PythonCodeToolConfig",
        "tables.PythonCodeResult",
        "tables.StorageFile",
        # The swept ConversationRecording DB row -- its audio file is already
        # counted via the "storage_files" external artifact.
        "tables.ConversationRecording",
        # Session-internal detail, implied by "sessions":
        "tables.GraphSessionMessage",
        "tables.SessionStorageFile",
        "tables.SessionWarningMessage",
        "tables.SessionTrigger",
        "tables.SessionPrincipal",
        "tables.AgentSessionMessage",
        "tables.TaskSessionMessage",
        "tables.UserSessionMessage",
        # FlowAssistant is a 1:1 extension of Graph, implied by "flow":
        "tables.FlowAssistant",
        # RAG family -- NaiveRag/GraphRag/BaseRagType and their own descendants,
        # implied by the already-mapped "knowledge_collections" (they all chain
        # back to a SourceCollection via BaseRagType.source_collection, CASCADE):
        "tables.BaseRagType",
        "tables.NaiveRag",
        "tables.NaiveRagDocumentConfig",
        "tables.NaiveRagChunk",
        "tables.NaiveRagEmbedding",
        "tables.NaiveRagPreviewChunk",
        "tables.GraphRag",
        "tables.GraphRagDocument",
        # RAG search-config sub-detail scoped to an Agent (1:1), implied by
        # "agents":
        "tables.NaiveRagSearchConfig",
        "tables.GraphRagBasicSearchConfig",
        "tables.GraphRagLocalSearchConfig",
        "tables.GraphRagGlobalSearchConfig",
        "tables.GraphRagDriftSearchConfig",
        # RAG search-config sub-detail scoped to a KnowledgeNode (graph-internal,
        # 1:1), implied by "flow":
        "tables.KnowledgeNodeNaiveRagSearchConfig",
        "tables.KnowledgeNodeGraphRagBasicSearchConfig",
        "tables.KnowledgeNodeGraphRagLocalSearchConfig",
        "tables.KnowledgeNodeGraphRagGlobalSearchConfig",
        "tables.KnowledgeNodeGraphRagDriftSearchConfig",
        # Agent/Task <-> tool/RAG M2M through-tables, implied by
        # "agents"/"tasks"/"tools":
        "tables.AgentMcpTools",
        "tables.AgentPythonCodeTools",
        "tables.AgentPythonCodeToolConfigs",
        "tables.AgentNaiveRag",
        "tables.AgentGraphRag",
        "tables.TaskMcpTools",
        "tables.TaskPythonCodeTools",
        "tables.TaskPythonCodeToolConfigs",
        # Webhook sub-detail, implied by "webhook_triggers":
        "tables.WebhookTriggerAuth",
        "tables.NgrokWebhookConfig",
        "tables.LocalhostWebhookConfig",
        # RealtimeChannel sub-detail, implied by "realtime_channels":
        "tables.TwilioChannel",
        # RealtimeAgent/RealtimeAgentDefinition are 1:1 extensions of
        # Agent/AgentDefinition, implied by "agents"/"agent_definitions":
        "tables.RealtimeAgent",
        "tables.RealtimeAgentDefinition",
        # Surface sub-detail, implied by "surfaces":
        "agents.AgentDefaultSurface",
        "agents.SurfacePythonTool",
        "agents.SurfaceMcpTool",
        "agents.SurfaceStorageItem",
        "agents.SurfaceKnowledge",
        "agents.SurfaceNaiveSearchConfig",
        "agents.SurfaceGraphBasicSearchConfig",
        "agents.SurfaceGraphLocalSearchConfig",
        "agents.SurfaceGraphGlobalSearchConfig",
        "agents.SurfaceGraphDriftSearchConfig",
        # InlineSurface is an ad-hoc surface owned by a TaskNode (graph-internal),
        # implied by "flow":
        "agents.InlineSurface",
        "agents.InlineSurfacePythonTool",
        "agents.InlineSurfaceMcpTool",
        "agents.InlineSurfaceStorageItem",
        "agents.InlineSurfaceKnowledge",
        "agents.InlineSurfaceNaiveSearchConfig",
        "agents.InlineSurfaceGraphBasicSearchConfig",
        "agents.InlineSurfaceGraphLocalSearchConfig",
        "agents.InlineSurfaceGraphGlobalSearchConfig",
        "agents.InlineSurfaceGraphDriftSearchConfig",
        # AgentInlineSurface is an ad-hoc surface owned by an AgentNode
        # (graph-internal), implied by "flow":
        "agents.AgentInlineSurface",
        "agents.AgentInlineSurfacePythonTool",
        "agents.AgentInlineSurfaceMcpTool",
        "agents.AgentInlineSurfaceStorageItem",
        "agents.AgentInlineSurfaceKnowledge",
        "agents.AgentInlineSurfaceNaiveSearchConfig",
        "agents.AgentInlineSurfaceGraphBasicSearchConfig",
        "agents.AgentInlineSurfaceGraphLocalSearchConfig",
        "agents.AgentInlineSurfaceGraphGlobalSearchConfig",
        "agents.AgentInlineSurfaceGraphDriftSearchConfig",
    }
)


def _linked_only_to(organization: Organization, *relations: str) -> Q:
    """Match rows linked to the organization through at least one relation and to no other organization through any of them."""
    linked = Q()
    linked_to_no_other_organization = Q()
    for relation in relations:
        points_at_organization = Q(**{f"{relation}__org": organization})
        linked |= points_at_organization
        linked_to_no_other_organization &= (
            Q(**{f"{relation}__isnull": True}) | points_at_organization
        )
    return linked & linked_to_no_other_organization


class TablesOrganizationDeletion:
    """Count, sweep and clean up the tables and agents data an organization delete removes beyond the Collector cascade."""

    def resource_names(self) -> dict[str, str]:
        return dict(TABLES_RESOURCE_NAMES)

    def excluded_resource_labels(self) -> frozenset[str]:
        return TABLES_EXCLUDED_RESOURCE_LABELS

    def count_external_artifacts(self, organization: Organization) -> dict[str, int]:
        """Count the MinIO objects under the organization's prefix, returning no count on a storage failure."""
        try:
            backend = get_storage_backend(
                organization_prefix=StorageManager.organization_prefix(organization.pk)
            )
            objects = backend.list_all_objects("")
        except Exception as exc:
            logger.warning(
                "TablesOrganizationDeletion storage_preview_failed org_id={org_id} error={error}",
                org_id=organization.pk,
                error=exc,
            )
            return {}
        return {STORAGE_FILES: len(objects)}

    def count(self, organization: Organization) -> OrganizationDeletionCounts:
        """Count what `sweep` would remove, plus the recording audio files it would orphan, without writing anything."""
        targets = self._sweep_querysets(organization)

        by_model: list[ModelCount] = []
        for model, queryset in (
            (Task, targets["tasks"]),
            (TemplateAgent, targets["template_agents"]),
            (RealtimeAgentChat, targets["realtime_agent_chats"]),
        ):
            count = queryset.count()
            if count:
                by_model.append(ModelCount(model=model._meta.label, count=count))

        collection_ids = list(targets["collections"].values_list("pk", flat=True))
        if collection_ids:
            by_model.append(
                ModelCount(model=SourceCollection._meta.label, count=len(collection_ids))
            )

        document_queryset = DocumentMetadata.all_objects.filter(
            source_collection_id__in=collection_ids
        )
        document_count = document_queryset.count()
        if document_count:
            by_model.append(ModelCount(model=DocumentMetadata._meta.label, count=document_count))

        # Predict which DocumentContent rows become unreferenced once the
        # sweep removes this organization's own DocumentMetadata, by excluding
        # rather than deleting those rows.
        content_ids = list(
            document_queryset.exclude(document_content__isnull=True)
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
            by_model.append(ModelCount(model=DocumentContent._meta.label, count=unreferenced_count))

        recording_count = ConversationRecording.objects.filter(
            rt_agent_chat__in=targets["realtime_agent_chats"]
        ).count()
        if recording_count:
            by_model.append(
                ModelCount(model=ConversationRecording._meta.label, count=recording_count)
            )

        return OrganizationDeletionCounts(
            by_model=by_model, external_counts={STORAGE_FILES: recording_count}
        )

    def sweep(self, organization: Organization) -> PostCommitCleanup:
        """Hard-delete the organization's knowledge collections, their now-unreferenced content and its deprecated linked rows, returning the storage purge to run after commit."""
        targets = self._sweep_querysets(organization)
        # Captured now: the Collector delete that follows clears organization.pk.
        storage_prefix = StorageManager.organization_prefix(organization.pk)

        recording_files = [
            name
            for name in ConversationRecording.objects.filter(
                rt_agent_chat__in=targets["realtime_agent_chats"]
            ).values_list("file", flat=True)
            if name
        ]

        collection_ids = list(targets["collections"].values_list("pk", flat=True))
        content_ids = list(
            DocumentMetadata.all_objects.filter(source_collection_id__in=collection_ids)
            .exclude(document_content__isnull=True)
            .values_list("document_content_id", flat=True)
            .distinct()
        )

        # A bulk QuerySet.delete() bypasses SoftDeleteMixin.delete(), so this
        # hard-deletes regardless of settings.SOFT_DELETE: a permanently
        # deleted organization must not leave its knowledge content behind.
        targets["collections"].delete()

        if content_ids:
            DocumentContent.objects.filter(id__in=content_ids).annotate(
                ref_count=Count("metadata_records")
            ).filter(ref_count=0).delete()

        targets["tasks"].delete()
        targets["template_agents"].delete()
        targets["realtime_agent_chats"].delete()

        def clean_up_external_artifacts() -> None:
            self._clean_up_external_artifacts(storage_prefix, recording_files)

        return clean_up_external_artifacts

    @staticmethod
    def _sweep_querysets(organization: Organization) -> dict[str, QuerySet]:
        """Return the querysets `count` and `sweep` both enumerate, so the two can never disagree."""
        # all_objects, not the soft-delete-filtered objects: a collection
        # soft-deleted before this delete started must still be swept, or its
        # DocumentContent survives as an orphan.
        return {
            "collections": SourceCollection.all_objects.filter(org=organization),
            "tasks": Task.objects.filter(_linked_only_to(organization, "crew", "agent")),
            "template_agents": TemplateAgent.objects.filter(
                _linked_only_to(organization, "llm_config", "fcm_llm_config")
            ),
            "realtime_agent_chats": RealtimeAgentChat.objects.filter(
                _linked_only_to(organization, "openai_config", "elevenlabs_config", "gemini_config")
            ),
        }

    @staticmethod
    def _clean_up_external_artifacts(storage_prefix: str, recording_files: list[str]) -> None:
        """Reset the platform default cache and purge the organization's MinIO prefix and swept recording files, logging rather than raising on failure."""
        try:
            # The cascade nulls Default* singleton FKs with a raw UPDATE, which
            # the process-level cache in DefaultBaseModel.save() never sees.
            DefaultBaseModel._load_cache.clear()
            backend = get_storage_backend(organization_prefix=storage_prefix)
            backend.delete_prefix("")
        except Exception as exc:
            logger.error(
                "TablesOrganizationDeletion cleanup_failed prefix={prefix} error={error}",
                prefix=storage_prefix,
                error=exc,
            )
        for name in recording_files:
            try:
                default_storage.delete(name)
            except Exception as exc:
                logger.error(
                    "TablesOrganizationDeletion recording_cleanup_failed name={name} error={error}",
                    name=name,
                    error=exc,
                )
