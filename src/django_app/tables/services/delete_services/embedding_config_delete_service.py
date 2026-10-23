from rbac.access.effective import EffectivePermissions
from rbac.models.enums import ResourceType
from tables.models import EmbeddingConfig
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    RefKind,
    UsageReport,
    build_reports,
)

# Both RAG kinds reach their SourceCollection and embedder by the same paths.
_RAG_MODELS = (GraphRag, NaiveRag)


class EmbeddingConfigDeleteService(BaseDeleteService):
    """Delete service for EmbeddingConfig entities.

    One bucket: the SourceCollections whose GraphRag or NaiveRag uses the
    config (KNOWLEDGE_SOURCES). A collection with both a GraphRag and a
    NaiveRag on the same embedder is one collection; BucketCollector folds the
    two rows.

    Deliberately not counted: the global `DefaultModels.memory_embedding_config`
    and `DefaultCrewConfig.embedding_config` singleton fields -- they have no
    ViewSet or resource type to check the caller's visibility against. Nor is
    the deprecated `tables.Crew`: it has no API or UI, and its FK to the config
    is SET_NULL.
    """

    model = EmbeddingConfig

    def collect_usage(
        self, ids: list[int], org_id: int, effective: EffectivePermissions
    ) -> dict[int, UsageReport]:
        """Collections referencing each config."""
        collections = BucketCollector.for_resource(ResourceType.KNOWLEDGE_SOURCES, effective)

        if ids:
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

        return build_reports(ids, [collections])
