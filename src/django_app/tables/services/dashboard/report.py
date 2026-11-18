from agents.models import AgentDefinition
from django.db.models import Count, Exists, OuterRef, Q, Sum
from plugins.models import GrantState, PluginGrant
from rbac.models import OrganizationUser, Role
from tables.models import (
    BaseRagType,
    ElevenLabsRealtimeConfig,
    EmbeddingConfig,
    GeminiRealtimeConfig,
    Graph,
    LLMConfig,
    McpTool,
    OpenAIRealtimeConfig,
    PythonCodeTool,
    SourceCollection,
    StorageFile,
)


def count_totals(org_id: int) -> dict[str, int]:
    files = StorageFile.objects.filter(org_id=org_id, item_type="file").aggregate(
        count=Count("pk"), size=Sum("size")
    )
    knowledge = _count_knowledge(org_id)
    return {
        "agents": AgentDefinition.objects.filter(org_id=org_id).count(),
        "flows": Graph.objects.filter(org_id=org_id).count(),
        "roles_builtin": Role.objects.filter(is_built_in=True).count(),
        "roles_custom": Role.objects.filter(org_id=org_id).count(),
        "users": OrganizationUser.objects.filter(org_id=org_id).count(),
        "knowledge_total": knowledge["total"],
        "knowledge_naive": knowledge["naive"],
        "knowledge_graph": knowledge["graph"],
        "knowledge_not_indexed": knowledge["not_indexed"],
        "files": files["count"],
        "files_bytes": files["size"] or 0,
        "llm_configs": LLMConfig.objects.filter(org_id=org_id).count(),
        "embedding_configs": EmbeddingConfig.objects.filter(org_id=org_id).count(),
        "realtime_configs": sum(
            model.objects.filter(org_id=org_id).count()
            for model in (OpenAIRealtimeConfig, ElevenLabsRealtimeConfig, GeminiRealtimeConfig)
        ),
        "tools_python": PythonCodeTool.objects.filter(org_id=org_id, built_in=False).count(),
        "tools_mcp": McpTool.objects.filter(org_id=org_id).count(),
        "plugins": PluginGrant.objects.filter(
            org_id=org_id, state__in=(GrantState.ACTIVE, GrantState.UPGRADING)
        ).count(),
    }


def _count_knowledge(org_id: int) -> dict[str, int]:
    def has_rag(rag_type: str) -> Exists:
        return Exists(
            BaseRagType.objects.filter(source_collection=OuterRef("pk"), rag_type=rag_type)
        )

    return (
        SourceCollection.objects.filter(org_id=org_id)
        .annotate(
            has_naive=has_rag(BaseRagType.RagType.NAIVE),
            has_graph=has_rag(BaseRagType.RagType.GRAPH),
        )
        .aggregate(
            total=Count("pk"),
            naive=Count("pk", filter=Q(has_naive=True)),
            graph=Count("pk", filter=Q(has_graph=True)),
            not_indexed=Count("pk", filter=Q(has_naive=False, has_graph=False)),
        )
    )
