import uuid
from copy import deepcopy

from tables.models import Graph, Crew
from tables.serializers.model_serializers import (
    CrewSerializer,
)
from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.serializers.graph import (
    GraphImportSerializer,
    EdgeImportSerializer,
    ConditionalEdgeImportSerializer,
)
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.constants import NODE_MAPPING_KEY
from tables.import_export.utils import ensure_unique_identifier
from tables.import_export.strategies.node_handlers import NODE_HANDLERS


class GraphStrategy(EntityImportExportStrategy):
    entity_type = EntityType.GRAPH
    serializer_class = GraphImportSerializer

    def get_instance(self, entity_id: int) -> Graph:
        return Graph.objects.filter(id=entity_id).first()

    def get_preview_data(self, instance: Graph) -> dict:
        return {"id": instance.id, "name": instance.name}

    def extract_dependencies_from_instance(
        self, instance: Graph
    ) -> dict[str, list[int]]:
        deps = {}
        deps[EntityType.CREW] = set(
            instance.crew_node_list.values_list("crew_id", flat=True)
        )
        deps[EntityType.WEBHOOK_TRIGGER] = list(
            instance.webhook_trigger_node_list.values_list(
                "webhook_trigger_id", flat=True
            )
        )
        deps[EntityType.GRAPH] = set(
            instance.subgraph_node_list.values_list("subgraph_id", flat=True)
        )
        deps[EntityType.LLM_CONFIG] = set(
            instance.code_agent_node_list.values_list("llm_config_id", flat=True)
        )
        return deps

    def export_entity(self, instance: Graph) -> dict:
        data = self.serializer_class(instance).data
        data["nodes"] = self._export_nodes(instance)
        return data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Graph:
        preserve_uuids = kwargs.get("preserve_uuids", False)
        import_data = data.copy()
        import_data["metadata"] = self._update_metadata(
            import_data["metadata"], id_mapper
        )

        if "name" in import_data:
            existing_names = Graph.objects.values_list("name", flat=True)
            import_data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        imported_uuid = import_data.pop("uuid", None)
        if preserve_uuids and imported_uuid:
            Graph.objects.filter(uuid=imported_uuid).update(uuid=uuid.uuid4())
            import_data["uuid"] = imported_uuid

        nodes_data = import_data.pop("nodes", [])
        edges_data = import_data.pop("edge_list", [])
        conditional_edges_data = import_data.pop("conditional_edge_list", [])

        serializer = self.serializer_class(data=import_data)
        serializer.is_valid(raise_exception=True)
        graph = serializer.save()

        node_mapper = IDMapper()

        # Pass 1: create all nodes and build the old→new node ID mapping
        self._create_nodes(nodes_data, graph, node_mapper, id_mapper)

        # Pass 2: create edges/conditional-edges with remapped node IDs,
        # then fix stale node-ID references in decision tables and metadata
        self._create_edges(edges_data, graph, node_mapper)
        self._create_conditional_edges(conditional_edges_data, graph, node_mapper)
        self._remap_decision_table_references(graph, node_mapper)
        self._update_metadata_node_ids(graph, node_mapper)

        return graph

    def _export_nodes(self, instance: Graph) -> list:
        nodes = []

        for node_type, config in NODE_HANDLERS.items():
            relation_name = config["relation"]
            serializer_class = config["serializer"]

            node_queryset = getattr(instance, relation_name).all()

            for node in node_queryset:
                node_data = serializer_class(node).data
                node_data["node_type"] = node_type
                nodes.append(node_data)

        return nodes

    def _create_nodes(
        self, nodes_data: list, graph: Graph, node_mapper: IDMapper, id_mapper: IDMapper
    ) -> None:
        for node_data in nodes_data:
            node_type = node_data.pop("node_type")
            # Backwards compat: old exports used "NoteNode"
            if node_type == "NoteNode":
                node_type = "GraphNote"
            old_id = node_data.get("id")

            config = NODE_HANDLERS[node_type]

            if "import_hook" in config:
                node = config["import_hook"](graph, node_data, id_mapper)
            else:
                node = self._default_import_node(graph, node_data, config)

            if old_id and node:
                node_mapper.map(NODE_MAPPING_KEY, old_id, node.id)

    def _create_edges(self, edges_data: list, graph: Graph, id_mapper: IDMapper):
        for edge_data in edges_data:
            edge_data["graph"] = graph.id
            edge_data["start_node_id"] = id_mapper.get(
                NODE_MAPPING_KEY, edge_data["start_node_id"]
            )
            edge_data["end_node_id"] = id_mapper.get(
                NODE_MAPPING_KEY, edge_data["end_node_id"]
            )

            serializer = EdgeImportSerializer(data=edge_data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

    def _create_conditional_edges(
        self, conditional_edges_data: list, graph: Graph, id_mapper: IDMapper
    ):
        for edge_data in conditional_edges_data:
            python_code_data = edge_data.pop("python_code", None)

            python_code_serializer = PythonCodeImportSerializer(data=python_code_data)
            python_code_serializer.is_valid(raise_exception=True)
            python_code = python_code_serializer.save()

            edge_data["graph"] = graph.id
            edge_data["python_code_id"] = python_code.id
            if edge_data["source_node_id"] is not None:
                edge_data["source_node_id"] = id_mapper.get(
                    NODE_MAPPING_KEY, edge_data["source_node_id"]
                )

            serializer = ConditionalEdgeImportSerializer(data=edge_data)
            serializer.is_valid(raise_exception=True)
            serializer.save()

    def _remap_decision_table_references(self, graph: Graph, id_mapper: IDMapper):
        for dt_node in graph.decision_table_node_list.all():
            updated = False

            if dt_node.default_next_node_id:
                new_id = id_mapper.get_or_none(
                    NODE_MAPPING_KEY, dt_node.default_next_node_id
                )
                if new_id:
                    dt_node.default_next_node_id = new_id
                    updated = True

            if dt_node.next_error_node_id:
                new_id = id_mapper.get_or_none(
                    NODE_MAPPING_KEY, dt_node.next_error_node_id
                )
                if new_id:
                    dt_node.next_error_node_id = new_id
                    updated = True

            if updated:
                dt_node.save(
                    update_fields=["default_next_node_id", "next_error_node_id"]
                )

            for group in dt_node.condition_groups.all():
                if group.next_node_id:
                    new_id = id_mapper.get_or_none(NODE_MAPPING_KEY, group.next_node_id)
                    if new_id:
                        group.next_node_id = new_id
                        group.save(update_fields=["next_node_id"])

    def _update_metadata_node_ids(self, graph: Graph, id_mapper: IDMapper):
        metadata = graph.metadata
        if not metadata:
            return

        nodes = metadata.get("nodes", [])
        changed = False

        for node in nodes:
            data = node.get("data") or {}
            node_id = data.get("id")
            if node_id is not None:
                new_id = id_mapper.get_or_none(NODE_MAPPING_KEY, node_id)
                if new_id and new_id != node_id:
                    data["id"] = new_id
                    changed = True

        if changed:
            graph.metadata = metadata
            graph.save(update_fields=["metadata"])

    def _default_import_node(self, graph: Graph, node_data: dict, config: dict):
        """Default import logic for simple nodes"""
        serializer_class = config["serializer"]
        node_data["graph"] = graph.id

        serializer = serializer_class(data=node_data)
        serializer.is_valid(raise_exception=True)
        return serializer.save()

    def _update_metadata(self, metadata: dict, id_mapper: IDMapper) -> dict:
        # TODO: Remove metadata when save functionality reworked
        metadata_copy = deepcopy(metadata)

        nodes = metadata_copy.get("nodes", [])
        for node in nodes:
            if node["type"] == "project":
                old_id = node["data"]["id"]
                new_id = id_mapper.get_or_none(EntityType.CREW, old_id)
                crew = Crew.objects.get(id=new_id)

                node["data"] = CrewSerializer(instance=crew).data
            if node["type"] == "webhook-trigger":
                old_id = node["data"]["webhook_trigger"]

                node["data"]["webhook_trigger"] = id_mapper.get_or_none(
                    EntityType.WEBHOOK_TRIGGER, old_id
                )
            if node["type"] == "subgraph":
                old_id = node["data"]["id"]
                new_id = id_mapper.get_or_none(EntityType.GRAPH, old_id)

                subgraph = Graph.objects.get(id=new_id)

                node["data"]["id"] = new_id
                node["data"]["name"] = subgraph.name
                node["data"]["description"] = subgraph.description
            if node["type"] == "telegram-trigger":
                node["data"]["telegram_bot_api_key"] = None

        return metadata_copy
