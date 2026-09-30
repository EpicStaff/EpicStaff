from tables.models import Crew, EmbeddingConfig
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.models.rbac_models.rbac_enums import ResourceType
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    RefKind,
    UsageReport,
    build_reports,
)
from tables.services.rbac.effective_permissions import EffectivePermissions

# Both RAG kinds reach their SourceCollection and embedder by the same paths.
_RAG_MODELS = (GraphRag, NaiveRag)


class EmbeddingConfigDeleteService(BaseDeleteService):
    """Delete service for EmbeddingConfig entities.

    Two buckets: the deprecated `tables.Crew` (PROJECTS) and the
    SourceCollections whose GraphRag or NaiveRag uses the config
    (KNOWLEDGE_SOURCES). A collection with both a GraphRag and a NaiveRag on
    the same embedder is one collection; BucketCollector folds the two rows.

    `tables.Crew` still counts as usage despite having no API or UI: existing
    flows with a CrewNode keep executing, so a config it references is a live
    dependency.

    Deliberately not counted: the global `DefaultModels.memory_embedding_config`
    and `DefaultCrewConfig.embedding_config` singleton fields -- they have no
    ViewSet or resource type to check the caller's visibility against.
    """

    model = EmbeddingConfig

    def collect_usage(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> dict[int, UsageReport]:
        """Crews and collections referencing each config."""
        crews = BucketCollector.for_resource(ResourceType.PROJECTS, effective)
        collections = BucketCollector.for_resource(
            ResourceType.KNOWLEDGE_SOURCES, effective
        )

        if ids:
            crews.add_rows(
                Crew.objects.filter(
                    org_id=org_id, embedding_config_id__in=ids
                ).values_list("embedding_config_id", "id", "name"),
                kind=RefKind.CREW,
            )
            for rag_model in _RAG_MODELS:
                collections.add_rows(
                    rag_model.objects.filter(
                        base_rag_type__source_collection__org_id=org_id,
                        embedder_id__in=ids,
                    )
                    .values_list(
                        "embedder_id",
                        "base_rag_type__source_collection__collection_id",
                        "base_rag_type__source_collection__collection_name",
                    )
                    .distinct(),
                    kind=RefKind.COLLECTION,
                )

        return build_reports(ids, [crews, collections])
