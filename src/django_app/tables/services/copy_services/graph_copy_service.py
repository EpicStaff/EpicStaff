from tables.import_export.utils import ensure_unique_identifier
from tables.models import Graph
from tables.models.graph_models import ConditionalEdge, Edge
from tables.services.copy_services.base_copy_service import BaseCopyService
from tables.services.copy_services.helpers import copy_python_code
from tables.services.copy_services.node_copy_handlers import NODE_COPY_HANDLERS


class GraphCopyService(BaseCopyService):
    """Copy service for Graph entities.

    Duplicates all scalar fields, then clones every node via NODE_COPY_HANDLERS,
    building a node_id_map. Edges and conditional edges are cloned with remapped
    node IDs. Two post-processing passes fix internal node ID references in
    DecisionTableNode fields and graph metadata JSON.
    """

    def copy(self, graph: Graph, name: str | None = None) -> Graph:
        existing_names = Graph.objects.values_list("name", flat=True)
        new_name = ensure_unique_identifier(
            base_name=name if name else graph.name,
            existing_names=existing_names,
        )

        new_graph = Graph.objects.create(
            name=new_name,
            description=graph.description,
            metadata=graph.metadata,
            time_to_live=graph.time_to_live,
            persistent_variables=graph.persistent_variables,
        )
        new_graph.labels.set(graph.labels.all())

        node_id_map: dict[int, int] = {}
        for _, (relation_name, handler) in NODE_COPY_HANDLERS.items():
            for node in getattr(graph, relation_name).all():
                new_node = handler(new_graph, node)
                node_id_map[node.id] = new_node.id

        for edge in graph.edge_list.all():
            Edge.objects.create(
                graph=new_graph,
                start_node_id=node_id_map.get(edge.start_node_id, edge.start_node_id),
                end_node_id=node_id_map.get(edge.end_node_id, edge.end_node_id),
                metadata=edge.metadata,
            )

        for cond_edge in graph.conditional_edge_list.all():
            new_code = copy_python_code(cond_edge.python_code)
            ConditionalEdge.objects.create(
                graph=new_graph,
                source_node_id=node_id_map.get(
                    cond_edge.source_node_id, cond_edge.source_node_id
                ),
                python_code=new_code,
                input_map=cond_edge.input_map,
                metadata=cond_edge.metadata,
            )

        self._remap_decision_table_references(new_graph, node_id_map)
        self._remap_metadata_node_ids(new_graph, node_id_map)

        return new_graph

    def _remap_decision_table_references(
        self, graph: Graph, node_id_map: dict[int, int]
    ) -> None:
        for dt_node in graph.decision_table_node_list.all():
            updated = False

            if (
                dt_node.default_next_node_id
                and dt_node.default_next_node_id in node_id_map
            ):
                dt_node.default_next_node_id = node_id_map[dt_node.default_next_node_id]
                updated = True

            if dt_node.next_error_node_id and dt_node.next_error_node_id in node_id_map:
                dt_node.next_error_node_id = node_id_map[dt_node.next_error_node_id]
                updated = True

            if updated:
                dt_node.save(
                    update_fields=["default_next_node_id", "next_error_node_id"]
                )

            for group in dt_node.condition_groups.all():
                if group.next_node_id and group.next_node_id in node_id_map:
                    group.next_node_id = node_id_map[group.next_node_id]
                    group.save(update_fields=["next_node_id"])

    def _remap_metadata_node_ids(
        self, graph: Graph, node_id_map: dict[int, int]
    ) -> None:
        metadata = graph.metadata
        if not metadata:
            return

        nodes = metadata.get("nodes", [])
        changed = False

        for node in nodes:
            data = node.get("data") or {}
            node_id = data.get("id")
            if node_id is not None and node_id in node_id_map:
                data["id"] = node_id_map[node_id]
                changed = True

        if changed:
            graph.metadata = metadata
            graph.save(update_fields=["metadata"])
