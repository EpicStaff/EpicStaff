from rbac.models.enums import ResourceType
from tables.models import EmbeddingConfig
from tables.models.knowledge_models.graphrag_models import GraphRag
from tables.models.knowledge_models.naive_rag_models import NaiveRag
from tables.services.delete_services.base_delete_service import BaseDeleteService
from tables.services.delete_services.usage import (
    BucketCollector,
    UsageReport,
    build_reports,
)

# Both RAG kinds reach their SourceCollection and embedder by the same paths.
_RAG_MODELS = (GraphRag, NaiveRag)


class EmbeddingConfigDeleteService(BaseDeleteService):
    """Delete service for EmbeddingConfig: usage is the collections whose RAG uses it.

    The global `DefaultModels` / `DefaultCrewConfig` fields are not counted: they
    have no resource type to check the caller's visibility against.
    """

    model = EmbeddingConfig

    def collect_usage(self, ids: list[int]) -> dict[int, UsageReport]:
        """Collections referencing each config."""
        collections = BucketCollector.for_resource(ResourceType.KNOWLEDGE_SOURCES, self.permissions)

        if ids:
            for rag_model in _RAG_MODELS:
                collections.add_rows(
                    rag_model.objects.filter(
                        base_rag_type__source_collection__org_id=self.org_id,
                        embedder_id__in=ids,
                    )
                    .values_list(
                        "embedder_id",
                        "base_rag_type__source_collection__collection_id",
                        "base_rag_type__source_collection__collection_name",
                    )
                    .distinct()
                )

        return build_reports(ids, [collections])
