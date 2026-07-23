import re
import uuid
from copy import deepcopy

from tables.models import Graph, Crew, GraphOrganization
from tables.models.label_models import Label
from tables.models.graph_models import ClassificationDecisionTablePrompt
from tables.serializers.model_serializers import CrewSerializer

from tables.import_export.strategies.base import EntityImportExportStrategy
from tables.import_export.strategies.nodes.node_maps import (
    NODE_RELATIONS,
    NODE_TYPE_TO_ENTITY_TYPE,
)
from tables.import_export.registry import entity_registry
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
            {
                *instance.webhook_trigger_node_list.values_list(
                    "webhook_trigger_id", flat=True
                ),
                *instance.telegram_trigger_node_list.values_list(
                    "webhook_trigger_id", flat=True
                ),
            }
        )
        deps[EntityType.GRAPH] = set(
            instance.subgraph_node_list.values_list("subgraph_id", flat=True)
        )
        deps[EntityType.LLM_CONFIG] = set(
            instance.code_agent_node_list.values_list("llm_config_id", flat=True)
        )
        deps[EntityType.LABEL] = set(instance.labels.values_list("id", flat=True))
        deps[EntityType.LLM_CONFIG] |= set(
            instance.classification_decision_table_node_list.values_list(
                "default_llm_config_id", flat=True
            )
        )
        deps[EntityType.LLM_CONFIG] |= set(
            ClassificationDecisionTablePrompt.objects.filter(
                cdt_node__graph=instance
            ).values_list("llm_config_id", flat=True)
        )
        deps[EntityType.LLM_CONFIG].discard(None)
        return deps

    def export_entity(self, instance: Graph) -> dict:
        data = self.serializer_class(instance).data
        data["nodes"] = self._export_nodes(instance)
        data["labels"] = list(instance.labels.values_list("id", flat=True))
        return data

    def create_entity(self, data: dict, id_mapper: IDMapper, **kwargs) -> Graph:
        preserve_uuids = kwargs.get("preserve_uuids", False)
        replace_existing = kwargs.get("replace_existing", False)
        import_labels = kwargs.get("import_labels", True)
        org_id = kwargs.get("org_id")
        import_data = data.copy()
        import_data["metadata"] = self.update_metadata(
            import_data["metadata"], id_mapper
        )

        if "name" in import_data:
            existing_names = Graph.objects.filter(org_id=org_id).values_list(
                "name", flat=True
            )
            import_data["name"] = ensure_unique_identifier(
                base_name=data["name"],
                existing_names=existing_names,
            )

        imported_uuid = import_data.pop("uuid", None)
        if preserve_uuids and imported_uuid:
            if replace_existing:
                Graph.objects.filter(uuid=imported_uuid).delete()
            else:
                Graph.objects.filter(uuid=imported_uuid).update(uuid=uuid.uuid4())
            import_data["uuid"] = imported_uuid

        nodes_data = import_data.pop("nodes", [])
        edges_data = import_data.pop("edge_list", [])
        conditional_edges_data = import_data.pop("conditional_edge_list", [])
        labels_data = import_data.pop("labels", [])

        import_data["org"] = org_id
        serializer = self.serializer_class(data=import_data)
        serializer.is_valid(raise_exception=True)
        graph = serializer.save()

        GraphOrganization.objects.get_or_create(graph=graph)

        self.recreate_graph_children(
            graph,
            {
                "nodes": nodes_data,
                "edge_list": edges_data,
                "conditional_edge_list": conditional_edges_data,
            },
            id_mapper,
        )

        if import_labels and labels_data:
            self._attach_labels(graph, id_mapper, labels_data)

        return graph

    def recreate_graph_children(
        self, graph: Graph, data: dict, id_mapper: IDMapper, is_partial: bool = False
    ) -> IDMapper:
        nodes_data = data.get("nodes", [])
        edges_data = data.get("edge_list", [])
        conditional_edges_data = data.get("conditional_edge_list", [])

        node_mapper = IDMapper()

        # Pass 1: create all nodes and build the old→new node ID mapping
        self._create_nodes(nodes_data, graph, node_mapper, id_mapper)

        # Pass 2: create edges/conditional-edges with remapped node IDs,
        # then fix stale node-ID references in decision tables and metadata
        self._create_edges(edges_data, graph, node_mapper)
        self._create_conditional_edges(conditional_edges_data, graph, node_mapper)
        self._remap_decision_table_references(graph, node_mapper)
        self._remap_classification_decision_table_references(graph, node_mapper)

        # Metadata remapping is only correct for full-graph imports/versioning,
        # where graph.metadata was rebuilt from the import and its node ids are
        # old export ids. In a partial import the metadata belongs to the
        # pre-existing graph; its node ids are real, current ids that collide
        # with the old export ids in node_mapper, so remapping them would
        # silently re-point existing nodes at the freshly imported duplicates.
        if not is_partial:
            self._update_metadata_node_ids(graph, node_mapper)

        # need only for versioning system
        return node_mapper

    def _export_nodes(self, instance: Graph) -> list:
        nodes = []

        for node_type, relation_name in NODE_RELATIONS.items():
            entity_type = NODE_TYPE_TO_ENTITY_TYPE[node_type]
            strategy = entity_registry.get_strategy(entity_type)

            node_queryset = getattr(instance, relation_name).all()

            for node in node_queryset:
                node_data = strategy.export_entity(node)
                node_data["node_type"] = node_type
                nodes.append(node_data)

        return nodes

    def _create_nodes(
        self, nodes_data: list, graph: Graph, node_mapper: IDMapper, id_mapper: IDMapper
    ) -> None:
        # Mirror the frontend's node numbering: a single graph-wide counter that
        # starts above the highest metadata["nodeNumber"] already present in the
        # graph, so imported nodes count up from the top instead of filling gaps
        # (which could reuse an existing number). Each numbered node also gets its
        # assigned number written back into metadata["nodeNumber"].
        counter = self._max_node_number(graph)

        for node_data in nodes_data:
            node_type = node_data.pop("node_type")
            # Backwards compat: old exports used "NoteNode"
            if node_type == "NoteNode":
                node_type = "GraphNote"
            old_id = node_data.get("id")

            if node_data.get("node_name"):
                counter += 1
                node_data["node_name"] = self._with_node_number(
                    node_data["node_name"], counter
                )
                metadata = node_data.get("metadata") or {}
                metadata["nodeNumber"] = counter
                node_data["metadata"] = metadata

            # Node strategies resolve their parent graph via
            # id_mapper.get_or_none(GRAPH, node_data["graph"]). The exported node
            # carries no "graph" key (it's write-only on the serializer), and the
            # parent graph's id mapping isn't registered yet (the import service
            # records it only after this method returns). Stamp the real graph id
            # onto the node and register an identity mapping for it, so the
            # strategy resolves the graph to this freshly-created instance.
            # Guard against overwriting a real GRAPH mapping (e.g. an imported
            # subgraph whose exported id happens to equal this graph's new id).
            node_data["graph"] = graph.id
            if not id_mapper.has_mapping(EntityType.GRAPH, graph.id):
                id_mapper.map(EntityType.GRAPH, graph.id, graph.id, was_created=False)

            entity_type = NODE_TYPE_TO_ENTITY_TYPE[node_type]
            strategy = entity_registry.get_strategy(entity_type)
            node = strategy.create_entity(node_data, id_mapper)

            if old_id and node:
                node_mapper.map(NODE_MAPPING_KEY, old_id, node.id)

    def _with_node_number(self, name: str, number: int) -> str:
        """Strip any trailing "#N" / "# N" suffix and append " #{number}"."""
        base = re.sub(r"\s*#\s*\d+$", "", name).strip()
        return f"{base} #{number}"

    def _max_node_number(self, graph: Graph) -> int:
        """Return the highest ``metadata["nodeNumber"]`` across all of the
        graph's nodes (0 if none)."""
        max_num = 0
        for relation in NODE_RELATIONS.values():
            if not hasattr(graph, relation):
                continue
            qs = getattr(graph, relation)
            if not hasattr(qs, "values_list"):
                continue
            model = qs.model
            if not any(
                f.name == "metadata"
                for f in model._meta.get_fields()
                if hasattr(f, "column")
            ):
                continue
            for metadata in qs.values_list("metadata", flat=True):
                if isinstance(metadata, dict):
                    number = metadata.get("nodeNumber")
                    # Exact type match: excludes bool (a subclass of int) without
                    # a separate isinstance(number, bool) guard.
                    if type(number) is int:
                        max_num = max(max_num, number)
        return max_num

    def _create_edges(self, edges_data: list, graph: Graph, id_mapper: IDMapper):
        for edge_data in edges_data:
            edge_data["start_node_id"] = id_mapper.get(
                NODE_MAPPING_KEY, edge_data["start_node_id"]
            )
            edge_data["end_node_id"] = id_mapper.get(
                NODE_MAPPING_KEY, edge_data["end_node_id"]
            )

            serializer = EdgeImportSerializer(data=edge_data)
            serializer.is_valid(raise_exception=True)
            serializer.save(graph=graph)

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

    def _remap_node_reference(self, old_node_id, node_mapper: IDMapper):
        """
        Resolve a stored node-id reference to its freshly-imported counterpart.

        Returns the remapped id when the referenced node was part of this import,
        otherwise ``None`` so the connection is dropped. Clearing is required for
        partial imports: a node imported on its own carries topology references
        (``default_next_node_id`` / ``next_error_node_id`` / group ``next_node_id``)
        that point to nodes outside the import scope. Keeping the raw id would
        silently wire the new node to an unrelated node in the target graph that
        happens to share that id.
        """
        if not old_node_id:
            return None
        return node_mapper.get_or_none(NODE_MAPPING_KEY, old_node_id)

    def _remap_decision_table_references(self, graph: Graph, node_mapper: IDMapper):
        # Only nodes created in this import — never touch pre-existing graph nodes,
        # whose references are valid as-is and must not be rewired.
        new_node_ids = set(node_mapper.get_new_ids(NODE_MAPPING_KEY))
        nodes = graph.decision_table_node_list.filter(id__in=new_node_ids)

        for dt_node in nodes:
            dt_node.default_next_node_id = self._remap_node_reference(
                dt_node.default_next_node_id, node_mapper
            )
            dt_node.next_error_node_id = self._remap_node_reference(
                dt_node.next_error_node_id, node_mapper
            )
            dt_node.save(update_fields=["default_next_node_id", "next_error_node_id"])

            for group in dt_node.condition_groups.all():
                new_id = self._remap_node_reference(group.next_node_id, node_mapper)
                if new_id != group.next_node_id:
                    group.next_node_id = new_id
                    group.save(update_fields=["next_node_id"])

    def _remap_classification_decision_table_references(
        self, graph: Graph, node_mapper: IDMapper
    ):
        new_node_ids = set(node_mapper.get_new_ids(NODE_MAPPING_KEY))
        nodes = graph.classification_decision_table_node_list.filter(
            id__in=new_node_ids
        )

        for cdt_node in nodes:
            cdt_node.default_next_node_id = self._remap_node_reference(
                cdt_node.default_next_node_id, node_mapper
            )
            cdt_node.next_error_node_id = self._remap_node_reference(
                cdt_node.next_error_node_id, node_mapper
            )
            cdt_node.save(update_fields=["default_next_node_id", "next_error_node_id"])

            for group in cdt_node.condition_groups.all():
                new_id = self._remap_node_reference(group.next_node_id, node_mapper)
                if new_id != group.next_node_id:
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

    def _attach_labels(
        self, graph: Graph, id_mapper: IDMapper, label_ids: list
    ) -> None:
        new_label_ids = [
            id_mapper.get(EntityType.LABEL, old_id) for old_id in label_ids
        ]
        if new_label_ids:
            graph.labels.add(*Label.objects.filter(id__in=new_label_ids))

    def update_metadata(self, metadata: dict, id_mapper: IDMapper) -> dict:
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
