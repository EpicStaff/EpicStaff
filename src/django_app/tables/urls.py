from django.urls import path, include
from rest_framework.routers import DefaultRouter

from tables.views.model_view_sets import (
    ConditionGroupModelViewSet,
    ConditionModelViewSet,
    ConditionalEdgeViewSet,
    CrewNodeViewSet,
    DecisionTableNodeModelViewSet,
    EdgeViewSet,
    GraphLightViewSet,
    GraphViewSet,
    PythonNodeViewSet,
    LLMNodeViewSet,
    StartNodeModelViewSet,
    RealtimeConfigModelViewSet,
    RealtimeSessionItemViewSet,
    RealtimeTranscriptionConfigModelViewSet,
    RealtimeTranscriptionModelViewSet,
    TemplateAgentReadWriteViewSet,
    LLMConfigReadWriteViewSet,
    ProviderReadWriteViewSet,
    LLMModelReadWriteViewSet,
    EmbeddingModelReadWriteViewSet,
    EmbeddingConfigReadWriteViewSet,
    AgentReadWriteViewSet,
    CrewReadWriteViewSet,
    TaskReadWriteViewSet,
    ToolConfigViewSet,
    PythonCodeToolViewSet,
    PythonCodeViewSet,
    PythonCodeResultReadViewSet,
    GraphSessionMessageReadOnlyViewSet,
    SourceCollectionViewSet,
    CopySourceCollectionViewSet,
    DocumentMetadataViewSet,
    MemoryViewSet,
    CrewTagViewSet,
    AgentTagViewSet,
    GraphTagViewSet,
    RealtimeModelViewSet,
    RealtimeAgentViewSet,
    RealtimeAgentChatViewSet,
)

from tables.views.views import (
    AnswerToLLM,
    EnvironmentConfig,
    InitRealtimeAPIView,
    RunPythonCodeAPIView,
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
    CollectionStatusAPIView,
    QuickstartView,
    delete_environment_config,
)

from tables.views.default_config import (
    DefaultConfigAPIView,
    DefaultRealtimeAgentConfigAPIView,
    DefaultToolConfigAPIView,
)

from tables.views.sse_views import RunSessionSSEView, RunSessionSSEViewSwagger

router = DefaultRouter()
router.register(r"template-agents", TemplateAgentReadWriteViewSet)
router.register(r"providers", ProviderReadWriteViewSet)
router.register(r"llm-models", LLMModelReadWriteViewSet)
router.register(r"llm-configs", LLMConfigReadWriteViewSet)
router.register(r"embedding-models", EmbeddingModelReadWriteViewSet)
router.register(r"embedding-configs", EmbeddingConfigReadWriteViewSet)
router.register(r"agents", AgentReadWriteViewSet)
router.register(r"crews", CrewReadWriteViewSet)
router.register(r"tasks", TaskReadWriteViewSet)
router.register(r"tools", ToolListRetrieveUpdateGenericViewSet)
router.register(r"tool-configs", ToolConfigViewSet)
router.register(r"python-code", PythonCodeViewSet)
router.register(r"python-code-tool", PythonCodeToolViewSet)
router.register(r"python-code-result", PythonCodeResultReadViewSet)
router.register(r"source-collections", SourceCollectionViewSet)
router.register(
    r"source-collection-copy",
    CopySourceCollectionViewSet,
    basename="source_collection_copy",
)
router.register(r"sources", DocumentMetadataViewSet)
# Graphs
router.register(r"graphs", GraphViewSet, basename="graphs")
router.register(r"crewnodes", CrewNodeViewSet)
router.register(r"pythonnodes", PythonNodeViewSet)
router.register(r"llmnodes", LLMNodeViewSet)
router.register(r"startnodes", StartNodeModelViewSet)

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
router.register(r"condition-group", ConditionGroupModelViewSet)
router.register(r"condition", ConditionModelViewSet)

router.register(r"sessions", SessionViewSet, basename="session")

urlpatterns = [
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
    path(
        "collection_status/<int:collection_id>/",
        CollectionStatusAPIView.as_view(),
        name="collection_status/",
    ),
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
]
