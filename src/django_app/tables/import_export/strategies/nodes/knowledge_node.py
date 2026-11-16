from rbac.authorship import resolve_author
from rest_framework.exceptions import ValidationError

from tables.exceptions import RagException
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.serializers.knowledge_node import (
    KnowledgeNodeImportSerializer,
)
from tables.import_export.serializers.surface_knowledge import resolve_collection_id
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.strategies.source_collection import RAG_KEYS
from tables.models import KnowledgeNode
from tables.models.knowledge_models import SourceCollection
from tables.serializers.graph_rag_serializers import (
    GraphBasicSearchConfigInputSerializer,
    GraphDriftSearchConfigInputSerializer,
    GraphGlobalSearchConfigInputSerializer,
    GraphLocalSearchConfigInputSerializer,
)
from tables.serializers.naive_rag_serializers import NaiveSearchConfigInputSerializer
from tables.services.rag_assignment_service import SearchConfigService
from tables.services.rag_registry import resolve_rag_in_collection

# Each search config block of a node in the file is checked by the serializer the
# knowledge node API checks it with, and written by the same service, so an import
# is held to the API's limits. The serializer takes only its own fields; any other
# key in the file is ignored. A field the block leaves out keeps the model default.
_SEARCH_CONFIG_BLOCKS = {
    "naive_search_config": (
        NaiveSearchConfigInputSerializer,
        SearchConfigService.update_node_naive_search_config,
    ),
    "graph_basic_search_config": (
        GraphBasicSearchConfigInputSerializer,
        SearchConfigService.update_node_graph_basic_search_config,
    ),
    "graph_local_search_config": (
        GraphLocalSearchConfigInputSerializer,
        SearchConfigService.update_node_graph_local_search_config,
    ),
    "graph_global_search_config": (
        GraphGlobalSearchConfigInputSerializer,
        SearchConfigService.update_node_graph_global_search_config,
    ),
    "graph_drift_search_config": (
        GraphDriftSearchConfigInputSerializer,
        SearchConfigService.update_node_graph_drift_search_config,
    ),
}


class KnowledgeNodeStrategy(EntityImportExportStrategy):
    entity_type = EntityType.KNOWLEDGE_NODE
    serializer_class = KnowledgeNodeImportSerializer

    def get_instance(self, entity_id: int) -> KnowledgeNode | None:
        return KnowledgeNode.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: KnowledgeNode) -> dict:
        return {"id": instance.id, "graph": instance.graph_id}

    def extract_dependencies_from_instance(self, instance: KnowledgeNode) -> dict:
        deps = {EntityType.GRAPH: [instance.graph_id]}
        if instance.source_collection_id:
            deps[EntityType.SOURCE_COLLECTION] = [instance.source_collection_id]
        return deps

    def export_entity(self, instance: KnowledgeNode) -> dict:
        return self.serializer_class(instance).data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> KnowledgeNode:
        """Create the node and its search configs.

        Raises:
            ValidationError: A search config block holds a value the knowledge node
                API refuses; keyed by the node and the block. The import's
                transaction rolls back, so nothing of the file is stored.
        """
        graph_id = id_mapper.get_or_none(EntityType.GRAPH, data.pop("graph", None))

        search_configs = self._validated_search_configs(
            {key: data.pop(key, None) for key in _SEARCH_CONFIG_BLOCKS}, data
        )

        # Files written before nodes carried the name have none; they relink by id alone.
        collection_name = data.pop("source_collection_name", None)
        old_collection_id = data.get("source_collection")
        collection_id = resolve_collection_id(
            old_collection_id, id_mapper, kwargs.get("org_id"), collection_name
        )
        source_collection = (
            SourceCollection.objects.filter(pk=collection_id).first()
            if collection_id is not None
            else None
        )
        data["source_collection"] = collection_id

        rag_type = data.get("rag_type")
        rag_id = data.get("rag_id")
        # A collection the file carried has new RAG ids; the import recorded the map.
        if (
            id_mapper.has_mapping(EntityType.SOURCE_COLLECTION, old_collection_id)
            and rag_type in RAG_KEYS
            and rag_id is not None
        ):
            rag_id = id_mapper.get_or_none(RAG_KEYS[rag_type], rag_id)
            data["rag_id"] = rag_id
        rag_ok = False
        if source_collection is not None and rag_type and rag_id is not None:
            try:
                resolve_rag_in_collection(rag_type, rag_id, source_collection)
                rag_ok = True
            except RagException:
                rag_ok = False
        if not rag_ok:
            data["rag_type"] = None
            data["rag_id"] = None

        serializer = self.serializer_class(data={**data, "graph": graph_id})
        serializer.is_valid(raise_exception=True)
        node = serializer.save(
            created_by=resolve_author(kwargs.get("user")),
            node_number=kwargs.get("node_number"),
        )

        for key, values in search_configs.items():
            _, write_config = _SEARCH_CONFIG_BLOCKS[key]
            try:
                write_config(node, **values)
            except ValidationError as error:
                # The two proportions are checked against each other only here, on
                # the row merged with the model defaults, as the API does.
                raise _search_config_error(data, key, error.detail) from error

        return node

    @staticmethod
    def _validated_search_configs(raw_configs: dict, node_data: dict) -> dict:
        """Return each block the file gives a value for, validated; empty ones are left out."""
        validated = {}
        for key, values in raw_configs.items():
            if not values:
                continue
            serializer_class, _ = _SEARCH_CONFIG_BLOCKS[key]
            serializer = serializer_class(data=values)
            if not serializer.is_valid():
                raise _search_config_error(node_data, key, serializer.errors)
            validated[key] = serializer.validated_data
        return validated


def _search_config_error(node_data: dict, block: str, detail) -> ValidationError:
    node_label = node_data.get("node_name") or node_data.get("id")
    return ValidationError({f'Knowledge node "{node_label}"': {block: detail}})
