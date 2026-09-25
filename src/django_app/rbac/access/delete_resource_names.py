from loguru import logger

RESOURCE_NAMES: dict[str, str] = {
    # user cascade
    "rbac.OrganizationUser": "memberships",
    "rbac.ApiKey": "api_keys",
    "rbac.PasswordResetToken": "password_reset_tokens",
    "tables.PythonCodeToolFavorite": "tool_favorites",
    "tables.McpToolFavorite": "tool_favorites",
    "tables.FlowAssistantConversation": "assistant_conversations",
    "tables.FlowAssistantMessage": "assistant_conversations",
    # org cascade -- direct
    "tables.Graph": "flow",
    "tables.Session": "sessions",
    "tables.Agent": "agents",
    "tables.Crew": "crews",
    "rbac.Role": "roles",
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
    # org cascade -- swept (deprecated, SET_NULL-only reachable, handled by
    # OrganizationManagementService's hand-rolled sweep, not the Collector)
    "tables.Task": "tasks",
    "tables.TemplateAgent": "template_agents",
    "tables.RealtimeAgentChat": "realtime_agent_chats",
}

# Deliberately excluded: graph-internal structure (implied by "flow"),
# tool sub-detail (implied by "tools"), role sub-detail (implied by
# "roles"), and DB bookkeeping for files already counted via the
# "storage_files" external artifact. Present here so the coverage-guard
# test can tell "known, meant to be silent" apart from "nobody mapped this
# yet".
KNOWN_EXCLUDED_LABELS: frozenset[str] = frozenset(
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
        "rbac.RolePermission",
        "tables.StorageFile",
        # The swept ConversationRecording DB row -- its audio file is already
        # counted via the "storage_files" external artifact (see
        # OrganizationManagementService.preview_delete/delete_organization).
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
        # The delete target's own row -- Collector.collect([instance]) always
        # includes the target itself in the cascade it reports, but the target
        # is already identified by organization_id/user_id, not an affected
        # resource.
        "rbac.Organization",
        "tables.User",
    }
)


def resource_name(label: str) -> str | None:
    """Friendly display name for a cascade row's model label, or None if it must not be reported at all."""
    mapped = RESOURCE_NAMES.get(label)
    if mapped is not None:
        return mapped
    if label in KNOWN_EXCLUDED_LABELS:
        return None
    logger.warning(
        "delete report: unmapped model label {label} -- add it to delete_resource_names.py",
        label=label,
    )
    return None
