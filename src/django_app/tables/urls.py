from django.urls import path, include
from rest_framework.routers import DefaultRouter

from tables.views.model_view_sets import (
    ClassificationDecisionTableNodeModelViewSet,
    ConditionalEdgeViewSet,
    CrewNodeViewSet,
    DecisionTableNodeModelViewSet,
    EdgeViewSet,
    EndNodeModelViewSet,
    GraphNoteViewSet,
    SubGraphNodeModelViewSet,
    GraphLightViewSet,
    GraphViewSet,
    GraphVersionViewSet,
    McpToolViewSet,
    NgrokWebhookConfigViewSet,
    PythonCodeToolConfigViewSet,
    PythonNodeViewSet,
    FileExtractorNodeViewSet,
    AudioTranscriptionNodeViewSet,
    CodeAgentNodeViewSet,
    StartNodeModelViewSet,
    RealtimeConfigModelViewSet,
    RealtimeSessionItemViewSet,
    RealtimeTranscriptionConfigModelViewSet,
    RealtimeTranscriptionModelViewSet,
    TelegramTriggerNodeFieldViewSet,
    TelegramTriggerNodeViewSet,
    TemplateAgentReadWriteViewSet,
    LLMConfigReadWriteViewSet,
    ProviderReadWriteViewSet,
    LLMModelReadWriteViewSet,
    EmbeddingModelReadWriteViewSet,
    EmbeddingConfigReadWriteViewSet,
    AgentViewSet,
    CrewReadWriteViewSet,
    TaskReadWriteViewSet,
    ToolConfigViewSet,
    PythonCodeToolViewSet,
    PythonCodeViewSet,
    PythonCodeResultReadViewSet,
    GraphSessionMessageReadOnlyViewSet,
    MemoryViewSet,
    CrewTagViewSet,
    AgentTagViewSet,
    GraphTagViewSet,
    RealtimeModelViewSet,
    RealtimeAgentViewSet,
    RealtimeAgentChatViewSet,
    GraphOrganizationViewSet,
    GraphOrganizationUserViewSet,
    VoiceSettingsView,
    TwilioPhoneNumbersView,
    TwilioConfigureWebhookView,
    WebhookTriggerNodeViewSet,
    WebhookTriggerViewSet,
    LabelViewSet,
    ScheduleTriggerNodeViewSet,
)

from tables.views.views import (
    AnswerToLLM,
    EnvironmentConfig,
    InitRealtimeAPIView,
    RegisterTelegramTriggerApiView,
    ProcessRagIndexingView,
    RegisterWebhooksApiView,
    RunPythonCodeAPIView,
    TelegramTriggerNodeAvailableFieldsView,
    ToolListRetrieveUpdateGenericViewSet,
    SessionViewSet,
    RunSession,
    GetUpdates,
    StopSession,
    CrewDeleteAPIView,
    DefaultLLMConfigAPIView,
    DefaultEmbeddingConfigAPIView,
    DefaultAgentConfigAPIView,
    DefaultCrewConfigAPIView,
    # CollectionStatusAPIView,
    QuickstartView,
    QuickstartApplyView,
    delete_environment_config,
    PythonNodeLastTestInputView,
)

from tables.views.default_config import (
    DefaultConfigAPIView,
    DefaultRealtimeAgentConfigAPIView,
    DefaultToolConfigAPIView,
    DefaultModelsAPIView,
)

from tables.views.knowledge_views.collection_management_views import (
    SourceCollectionViewSet,
)
from tables.views.knowledge_views.document_management_views import (
    DocumentManagementViewSet,
    DocumentViewSet,
    CollectionDocumentsViewSet,
)
from tables.views.knowledge_views.naive_rag_views import (
    NaiveRagViewSet,
    NaiveRagDocumentConfigViewSet,
    ProcessNaiveRagDocumentChunkingView,
    NaiveRagChunkViewSet,
    NaiveRagChunkPreviewView,
    NaiveRagChunkSearchView,
    NaiveRagPreviewChunkBulkByIdsView,
)
from tables.views.knowledge_views.graph_rag_views import (
    GraphRagViewSet,
)


from tables.views.storage_views import StorageAPIView
from tables.views.sse_views import (
    RunSessionSSEView,
    RunSessionSSEViewSwagger,
    FilteredRunSessionSSEView,
)
from tables.views.flow_assistant_views import (
    FlowAssistantAuditView,
    FlowAssistantCancelView,
    FlowAssistantConfigView,
    FlowAssistantConversationsView,
    FlowAssistantConversationView,
    FlowAssistantSendMessageView,
    FlowAssistantStreamView,
)

from tables.views.organization_admin_views import OrganizationAdminViewSet
from tables.views.role_admin_views import (
    OrgScopedRoleAdminViewSet,
    RoleAdminViewSet,
)
from tables.views.user_management_views import (
    OrganizationMembershipAdminViewSet,
    UserAdminViewSet,
)

router = DefaultRouter()
router.register(r"template-agents", TemplateAgentReadWriteViewSet)
router.register(r"providers", ProviderReadWriteViewSet)
router.register(r"llm-models", LLMModelReadWriteViewSet)
router.register(r"llm-configs", LLMConfigReadWriteViewSet)
router.register(r"embedding-models", EmbeddingModelReadWriteViewSet)
router.register(r"embedding-configs", EmbeddingConfigReadWriteViewSet)
router.register(r"agents", AgentViewSet)
router.register(r"crews", CrewReadWriteViewSet)
router.register(r"tasks", TaskReadWriteViewSet)
router.register(r"tools", ToolListRetrieveUpdateGenericViewSet)
router.register(r"tool-configs", ToolConfigViewSet)
router.register(r"python-code", PythonCodeViewSet)
router.register(r"python-code-tool", PythonCodeToolViewSet)
router.register(r"python-code-result", PythonCodeResultReadViewSet)
router.register(
    r"source-collections", SourceCollectionViewSet, basename="sourcecollection"
)

router.register(r"documents", DocumentViewSet, basename="document")
collection_documents_viewset = CollectionDocumentsViewSet.as_view({"get": "list"})

# Graphs
router.register(r"graphs", GraphViewSet, basename="graphs")
router.register(r"crewnodes", CrewNodeViewSet)
router.register(r"pythonnodes", PythonNodeViewSet)
router.register(r"file-extractor-nodes", FileExtractorNodeViewSet)
router.register(r"audio-transcription-nodes", AudioTranscriptionNodeViewSet)
router.register(r"startnodes", StartNodeModelViewSet)
router.register(r"endnodes", EndNodeModelViewSet)
router.register(r"subgraph-nodes", SubGraphNodeModelViewSet)
router.register(r"code-agent-nodes", CodeAgentNodeViewSet)

router.register(r"edges", EdgeViewSet)
router.register(r"conditionaledges", ConditionalEdgeViewSet)
router.register(r"graph-session-messages", GraphSessionMessageReadOnlyViewSet)
router.register(r"memory", MemoryViewSet)

router.register(r"crew-tags", CrewTagViewSet)
router.register(r"agent-tags", AgentTagViewSet)
router.register(r"graph-tags", GraphTagViewSet)
router.register(r"graph-light", GraphLightViewSet, basename="graphs-light")
router.register(r"graph-versions", GraphVersionViewSet, basename="graph-versions")
router.register(r"realtime-models", RealtimeModelViewSet)
router.register(r"realtime-model-configs", RealtimeConfigModelViewSet)
router.register(r"realtime-transcription-models", RealtimeTranscriptionModelViewSet)
router.register(
    r"realtime-transcription-model-configs", RealtimeTranscriptionConfigModelViewSet
)
router.register(r"realtime-session-items", RealtimeSessionItemViewSet)
router.register(r"realtime-agents", RealtimeAgentViewSet)
router.register(r"realtime-agent-chats", RealtimeAgentChatViewSet)
router.register(r"decision-table-node", DecisionTableNodeModelViewSet)
router.register(
    r"classification-decision-table-node", ClassificationDecisionTableNodeModelViewSet
)

router.register(r"sessions", SessionViewSet, basename="session")
router.register(r"mcp-tools", McpToolViewSet)
router.register(r"graph-organizations", GraphOrganizationViewSet)
router.register(r"graph-organization-users", GraphOrganizationUserViewSet)
router.register(r"naive-rag-document-chunks", NaiveRagChunkViewSet)
router.register(r"webhook-trigger-nodes", WebhookTriggerNodeViewSet)
router.register(r"webhook-triggers", WebhookTriggerViewSet)
router.register(r"telegram-trigger-nodes", TelegramTriggerNodeViewSet)
router.register(r"telegram-trigger-node-fields", TelegramTriggerNodeFieldViewSet)
router.register(r"python-code-tool-configs", PythonCodeToolConfigViewSet)
router.register(r"graph-notes", GraphNoteViewSet)
router.register(r"ngrok-config", NgrokWebhookConfigViewSet)
router.register(r"schedule-trigger-nodes", ScheduleTriggerNodeViewSet)

router.register(r"labels", LabelViewSet)
router.register(r"storage", StorageAPIView, basename="storage")

admin_router = DefaultRouter()
admin_router.register(
    r"organizations", OrganizationAdminViewSet, basename="admin-organization"
)
admin_router.register(r"users", UserAdminViewSet, basename="admin-user")
admin_router.register(r"roles", RoleAdminViewSet, basename="admin-role")

urlpatterns = [
    path(
        "documents/bulk-delete/",
        DocumentManagementViewSet.as_view({"post": "bulk_delete"}),
        name="document-bulk-delete",
    ),
    path(
        "admin/organizations/<int:org_id>/users/",
        OrganizationMembershipAdminViewSet.as_view({"get": "list", "post": "create"}),
        name="admin-org-users-list",
    ),
    path(
        "admin/organizations/<int:org_id>/users/<int:user_id>/",
        OrganizationMembershipAdminViewSet.as_view(
            {"patch": "partial_update", "delete": "destroy"}
        ),
        name="admin-org-users-detail",
    ),
    path(
        "admin/organizations/<int:org_id>/assign-users/",
        OrganizationMembershipAdminViewSet.as_view({"post": "assign_users"}),
        name="admin-org-users-assign",
    ),
    path(
        "admin/organizations/<int:org_id>/roles/",
        OrgScopedRoleAdminViewSet.as_view({"get": "list"}),
        name="admin-org-roles-list",
    ),
    path("admin/", include(admin_router.urls)),
    path("", include(router.urls)),
    path("run-session/", RunSession.as_view(), name="run-session"),
    path("answer-to-llm/", AnswerToLLM.as_view(), name="answer-to-llm"),
    path(
        "sessions/<int:session_id>/get-updates/",
        GetUpdates.as_view(),
        name="get-updates",
    ),
    path("sessions/<int:session_id>/stop/", StopSession.as_view(), name="stop-session"),
    path("crews/<int:id>/delete/", CrewDeleteAPIView.as_view(), name="delete-crew"),
    path(
        "environment/config/",
        EnvironmentConfig.as_view(),
        name="environment_config",
    ),
    path(
        "environment/config/<str:key>/",
        delete_environment_config,
        name="delete_environment_config",
    ),
    path(
        "run-python-code/",
        RunPythonCodeAPIView.as_view(),
        name="run-python-code",
    ),
    path(
        "pythonnodes/<int:pk>/last-session-input/",
        PythonNodeLastTestInputView.as_view(),
        name="python-node-last-session-input",
    ),
    path(
        "init-realtime/",
        InitRealtimeAPIView.as_view(),
        name="init-realtime",
    ),
    # path(
    #     "collection_statuses/",
    #     CollectionStatusAPIView.as_view(),
    #     name="collection_statuses/",
    # ),
    path("default-config/", DefaultConfigAPIView.as_view(), name="default_config"),
    path(
        "default-llm-config/",
        DefaultLLMConfigAPIView.as_view(),
        name="default_llm_config",
    ),
    path(
        "default-embedding-config/",
        DefaultEmbeddingConfigAPIView.as_view(),
        name="default_embedding_config",
    ),
    path(
        "default-agent-config/",
        DefaultAgentConfigAPIView.as_view(),
        name="default_agent_config",
    ),
    path(
        "default-reailtime-config/",
        DefaultRealtimeAgentConfigAPIView.as_view(),
        name="default_reailtime_config",
    ),
    path(
        "default-crew-config/",
        DefaultCrewConfigAPIView.as_view(),
        name="default_crew_config",
    ),
    path(
        "default-tool-config/",
        DefaultToolConfigAPIView.as_view(),
        name="default_tool_config",
    ),
    path("default-models/", DefaultModelsAPIView.as_view(), name="default_models"),
    path("quickstart/apply/", QuickstartApplyView.as_view(), name="quickstart_apply"),
    path("quickstart/", QuickstartView.as_view(), name="quickstart"),
    path(
        "run-session/subscribe/<int:session_id>/",
        RunSessionSSEView.as_view(),
        name="run-session-subscribe",
    ),
    path(
        "run-session/subscribe/<int:session_id>/filtered/",
        FilteredRunSessionSSEView.as_view(),
        name="run-session-subscribe-filtered",
    ),
    path(
        "run-session/subscribe/<int:session_id>/swagger/",
        RunSessionSSEViewSwagger.as_view(),
        name="run-session-subscribe-swagger",
    ),
    # Chunking preview endpoints
    path(
        "naive-rag/<int:naive_rag_id>/document-configs/<int:document_config_id>/process-chunking/",
        ProcessNaiveRagDocumentChunkingView.as_view(),
        name="process-document-chunking",
    ),
    path(
        "naive-rag/<int:naive_rag_id>/document-configs/<int:document_config_id>/chunks/search/",
        NaiveRagChunkSearchView.as_view(),
        name="naive-rag-chunks-search",
    ),
    path(
        "naive-rag/<int:naive_rag_id>/document-configs/<int:document_config_id>/chunks/by-ids/",
        NaiveRagPreviewChunkBulkByIdsView.as_view(),
        name="naive-rag-chunks-by-ids",
    ),
    path(
        "naive-rag/<int:naive_rag_id>/document-configs/<int:document_config_id>/chunks/",
        NaiveRagChunkPreviewView.as_view(),
        name="naive-rag-chunks-preview",
    ),
    path(
        "process-rag-indexing/",
        ProcessRagIndexingView.as_view(),
        name="process-rag-indexing",
    ),
    path(
        "documents/source-collection/<str:collection_id>/upload/",
        DocumentManagementViewSet.as_view({"post": "upload_documents"}),
        name="document-upload",
    ),
    path(
        "source-collections/<str:collection_id>/documents/",
        collection_documents_viewset,
        name="collection-documents",
    ),
    # NaiveRag endpoints
    path(
        "naive-rag/collections/<str:collection_id>/naive-rag/",
        NaiveRagViewSet.as_view(
            {"post": "create_or_update", "get": "get_by_collection"}
        ),
        name="naive-rag-collection",
    ),
    path(
        "naive-rag/<int:pk>/",
        NaiveRagViewSet.as_view({"get": "retrieve", "delete": "destroy"}),
        name="naive-rag-detail",
    ),
    path(
        "naive-rag/<int:naive_rag_id>/document-configs/initialize/",
        NaiveRagViewSet.as_view({"post": "initialize_configs"}),
        name="naive-rag-initialize-configs",
    ),
    path(
        "naive-rag/<str:naive_rag_id>/document-configs/",
        NaiveRagDocumentConfigViewSet.as_view({"get": "list_configs"}),
        name="document-config-list",
    ),
    path(
        "naive-rag/<str:naive_rag_id>/document-configs/<int:pk>/",
        NaiveRagDocumentConfigViewSet.as_view(
            {"get": "retrieve", "put": "update", "delete": "destroy"}
        ),
        name="document-config-detail",
    ),
    path(
        "naive-rag/<str:naive_rag_id>/document-configs/bulk-update/",
        NaiveRagDocumentConfigViewSet.as_view({"put": "bulk_update"}),
        name="document-config-bulk-update",
    ),
    path(
        "naive-rag/<str:naive_rag_id>/document-configs/bulk-delete/",
        NaiveRagDocumentConfigViewSet.as_view({"post": "bulk_delete"}),
        name="document-config-bulk-delete",
    ),
    # GraphRag endpoints
    path(
        "graph-rag/collections/<str:collection_id>/graph-rag/",
        GraphRagViewSet.as_view(
            {"post": "create_or_update", "get": "get_by_collection"}
        ),
        name="graph-rag-collection",
    ),
    path(
        "graph-rag/<int:pk>/",
        GraphRagViewSet.as_view({"get": "retrieve", "delete": "destroy"}),
        name="graph-rag-detail",
    ),
    path(
        "graph-rag/<int:pk>/index-config/",
        GraphRagViewSet.as_view({"put": "update_index_config"}),
        name="graph-rag-index-config",
    ),
    path(
        "graph-rag/<int:pk>/documents/bulk-delete/",
        GraphRagViewSet.as_view({"post": "remove_documents"}),
        name="graph-rag-documents-bulk-delete",
    ),
    path(
        "graph-rag/<int:pk>/documents/<int:document_id>/",
        GraphRagViewSet.as_view({"delete": "delete_document"}),
        name="graph-rag-document-delete",
    ),
    path(
        "graph-rag/<int:pk>/documents/list/",
        GraphRagViewSet.as_view({"get": "list_documents"}),
        name="graph-rag-documents-list",
    ),
    path(
        "graph-rag/<int:pk>/documents/initialize/",
        GraphRagViewSet.as_view({"post": "initialize_documents"}),
        name="graph-rag-documents-initialize",
    ),
    path(
        "telegram-trigger-available-fields/",
        TelegramTriggerNodeAvailableFieldsView.as_view(),
        name="telegram-trigger-available-fields",
    ),
    path(
        "register-telegram-trigger/",
        RegisterTelegramTriggerApiView.as_view(),
        name="register-telegram-trigger",
    ),
    path(
        "register-webhooks/",
        RegisterWebhooksApiView.as_view(),
        name="register-webhooks",
    ),
    path(
        "voice-settings/",
        VoiceSettingsView.as_view(),
        name="voice-settings",
    ),
    path(
        "twilio/phone-numbers/",
        TwilioPhoneNumbersView.as_view(),
        name="twilio-phone-numbers",
    ),
    path(
        "twilio/configure-webhook/",
        TwilioConfigureWebhookView.as_view(),
        name="twilio-configure-webhook",
    ),
    # Flow Assistant endpoints
    path(
        "flow-assistants/audit/conversations/",
        FlowAssistantAuditView.as_view(),
        name="flow-assistant-audit-conversations",
    ),
    path(
        "flow-assistants/<int:graph_id>/",
        FlowAssistantConfigView.as_view(),
        name="flow-assistant-config",
    ),
    path(
        "flow-assistants/<int:graph_id>/conversations/",
        FlowAssistantConversationsView.as_view(),
        name="flow-assistant-conversations",
    ),
    path(
        "flow-assistants/<int:graph_id>/conversations/<int:conversation_id>/",
        FlowAssistantConversationView.as_view(),
        name="flow-assistant-conversation",
    ),
    path(
        "flow-assistants/<int:graph_id>/conversations/<int:conversation_id>/messages/",
        FlowAssistantSendMessageView.as_view(),
        name="flow-assistant-send-message",
    ),
    path(
        "flow-assistants/<int:graph_id>/conversations/<int:conversation_id>/stream/",
        FlowAssistantStreamView.as_view(),
        name="flow-assistant-stream",
    ),
    path(
        "flow-assistants/<int:graph_id>/conversations/<int:conversation_id>/cancel/",
        FlowAssistantCancelView.as_view(),
        name="flow-assistant-cancel",
    ),
]
