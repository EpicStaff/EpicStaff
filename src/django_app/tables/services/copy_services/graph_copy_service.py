from django.db import transaction
from rbac.authorship import record_last_edits, resolve_author
from tables.models import Graph, Label
from tables.models.graph_models import Edge, StartNode
from tables.services.copy_services.base_copy_service import BaseCopyService
from tables.services.copy_services.helpers import next_copy_name
from tables.services.copy_services.node_copy_handlers import NODE_COPY_HANDLERS
from tables.services.persistent_variables_service import PersistentVariablesService


class GraphCopyService(BaseCopyService):
    """Copy a Graph with its nodes (via NODE_COPY_HANDLERS) and its edges, remapping node ids.

    Node ids stored inside decision-table nodes are remapped to the copies too. The acting
    user is recorded as the last editor of the new graph and of every new node.
    """

    def copy(
        self,
        graph: Graph,
        name: str | None = None,
        org_id: int | None = None,
        user=None,
    ) -> Graph:
        target_org_id = org_id if org_id is not None else graph.org_id
        base_name = name if name else graph.name

        with transaction.atomic():
            new_graph = Graph.objects.create(
                name=next_copy_name(Graph, org_id=target_org_id, base_name=base_name),
                description=graph.description,
                metadata=graph.metadata,
                time_to_live=graph.time_to_live,
                enable_persistent_variables=graph.enable_persistent_variables,
                org_id=target_org_id,
                created_by=resolve_author(user),
            )
        new_graph.labels.set(graph.labels.filter(scope=Label.Scope.FLOW))
        source_start = StartNode.objects.filter(graph=graph).first()
        PersistentVariablesService().seed_for_copy(
            new_graph, source_start.variables if source_start else {}
        )

        node_id_map: dict[int, int] = {}
        new_nodes = []
        for relation_name, handler in NODE_COPY_HANDLERS.values():
            for node in getattr(graph, relation_name).all():
                new_node = handler(new_graph, node, user=user)
                node_id_map[node.id] = new_node.id
                new_nodes.append(new_node)

        for edge in graph.edge_list.all():
            Edge.objects.create(
                graph=new_graph,
                start_node_id=node_id_map.get(edge.start_node_id, edge.start_node_id),
                end_node_id=node_id_map.get(edge.end_node_id, edge.end_node_id),
                metadata=edge.metadata,
            )

        self._remap_decision_table_references(new_graph, node_id_map)
        self._remap_classification_decision_table_references(new_graph, node_id_map)
        record_last_edits([new_graph, *new_nodes], user)

        return new_graph

    def _remap_decision_table_references(self, graph: Graph, node_id_map: dict[int, int]) -> None:
        for dt_node in graph.decision_table_node_list.all():
            updated = False

            if dt_node.default_next_node_id and dt_node.default_next_node_id in node_id_map:
                dt_node.default_next_node_id = node_id_map[dt_node.default_next_node_id]
                updated = True

            if dt_node.next_error_node_id and dt_node.next_error_node_id in node_id_map:
                dt_node.next_error_node_id = node_id_map[dt_node.next_error_node_id]
                updated = True

            if updated:
                dt_node.save(update_fields=["default_next_node_id", "next_error_node_id"])

            for group in dt_node.condition_groups.all():
                if group.next_node_id and group.next_node_id in node_id_map:
                    group.next_node_id = node_id_map[group.next_node_id]
                    group.save(update_fields=["next_node_id"])

    def _remap_classification_decision_table_references(
        self, graph: Graph, node_id_map: dict[int, int]
    ) -> None:
        for cdt_node in graph.classification_decision_table_node_list.all():
            updated = False

            if cdt_node.default_next_node_id and cdt_node.default_next_node_id in node_id_map:
                cdt_node.default_next_node_id = node_id_map[cdt_node.default_next_node_id]
                updated = True

            if cdt_node.next_error_node_id and cdt_node.next_error_node_id in node_id_map:
                cdt_node.next_error_node_id = node_id_map[cdt_node.next_error_node_id]
                updated = True

            if updated:
                cdt_node.save(update_fields=["default_next_node_id", "next_error_node_id"])

            for group in cdt_node.condition_groups.all():
                if group.next_node_id and group.next_node_id in node_id_map:
                    group.next_node_id = node_id_map[group.next_node_id]
                    group.save(update_fields=["next_node_id"])
