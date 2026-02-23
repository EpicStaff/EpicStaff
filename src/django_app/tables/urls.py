from django.urls import path, include
from rest_framework.routers import DefaultRouter

from tables.views.model_view_sets import (
    ConditionalEdgeViewSet,
    CrewNodeViewSet,
    DecisionTableNodeModelViewSet,
    EdgeViewSet,
    EndNodeModelViewSet,
    SubGraphNodeModelViewSet,
    GraphLightViewSet,
    GraphViewSet,
    McpToolViewSet,
    PythonCodeToolConfigFieldViewSet,
    PythonCodeToolConfigViewSet,
    PythonNodeViewSet,
    FileExtractorNodeViewSet,
    AudioTranscriptionNodeViewSet,
    LLMNodeViewSet,
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
    GraphFileViewSet,
    OrganizationViewSet,
    OrganizationUserViewSet,
    GraphOrganizationViewSet,
    GraphOrganizationUserViewSet,
    WebhookTriggerNodeViewSet,
    WebhookTriggerViewSet,
)

from tables.views.views import (
    AnswerToLLM,
    EnvironmentConfig,
    InitRealtimeAPIView,
    RegisterTelegramTriggerApiView,
    ProcessRagIndexingView,
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
    delete_environment_config,
)

from tables.views.default_config import (
    DefaultConfigAPIView,
    DefaultRealtimeAgentConfigAPIView,
    DefaultToolConfigAPIView,
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
)


from tables.views.sse_views import RunSessionSSEView, RunSessionSSEViewSwagger

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
router.register(r"graph-files", GraphFileViewSet)
router.register(r"crewnodes", CrewNodeViewSet)
router.register(r"pythonnodes", PythonNodeViewSet)
router.register(r"file-extractor-nodes", FileExtractorNodeViewSet)
router.register(r"audio-transcription-nodes", AudioTranscriptionNodeViewSet)
router.register(r"llmnodes", LLMNodeViewSet)
router.register(r"startnodes", StartNodeModelViewSet)
router.register(r"endnodes", EndNodeModelViewSet)
router.register(r"subgraph-nodes", SubGraphNodeModelViewSet)

router.register(r"edges", EdgeViewSet)
router.register(r"conditionaledges", ConditionalEdgeViewSet)
router.register(r"graph-session-messages", GraphSessionMessageReadOnlyViewSet)
router.register(r"memory", MemoryViewSet)

router.register(r"crew-tags", CrewTagViewSet)
router.register(r"agent-tags", AgentTagViewSet)
router.register(r"graph-tags", GraphTagViewSet)
router.register(r"graph-light", GraphLightViewSet, basename="graphs-light")
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

router.register(r"sessions", SessionViewSet, basename="session")
router.register(r"mcp-tools", McpToolViewSet)
router.register(r"organizations", OrganizationViewSet)
router.register(r"organization-users", OrganizationUserViewSet)
router.register(r"graph-organizations", GraphOrganizationViewSet)
router.register(r"graph-organization-users", GraphOrganizationUserViewSet)
router.register(r"naive-rag-document-chunks", NaiveRagChunkViewSet)
router.register(r"webhook-trigger-nodes", WebhookTriggerNodeViewSet)
router.register(r"webhook-triggers", WebhookTriggerViewSet)
router.register(r"telegram-trigger-nodes", TelegramTriggerNodeViewSet)
router.register(r"telegram-trigger-node-fields", TelegramTriggerNodeFieldViewSet)
router.register(r"python-code-tool-configs", PythonCodeToolConfigViewSet)
router.register(r"python-code-tool-config-fields", PythonCodeToolConfigFieldViewSet)

urlpatterns = [
    path(
        "documents/bulk-delete/",
        DocumentManagementViewSet.as_view({"post": "bulk_delete"}),
        name="document-bulk-delete",
    ),
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
    path("quickstart/", QuickstartView.as_view(), name="quickstart"),
    path(
        "run-session/subscribe/<int:session_id>/",
        RunSessionSSEView.as_view(),
        name="run-session-subscribe",
    ),
    path(
        "run-session/subscribe/<int:session_id>/swagger/",
        RunSessionSSEViewSwagger.as_view(),
        name="run-session-subscribe-swagger",
    ),
    path(
        "process-document-chunking/",
        ProcessNaiveRagDocumentChunkingView.as_view(),
        name="process-document-chunking",
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
]
