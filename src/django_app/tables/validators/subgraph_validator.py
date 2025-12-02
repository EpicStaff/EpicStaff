from tables.exceptions import SubGraphValidationError
from tables.models import Graph, SubGraphNode


class SubGraphValidator:
    """
    Validates that no Graph instances are involved in recursive (cyclic) subgraph relationships.
    """

    def validate(self, graph: Graph):
        """
        Checks graph for cyclic references via SubGraphNode relations.
        Raises SubGraphValidationError if any recursion is detected.
        """
        cycle_path = self._find_cycle(graph)
        if cycle_path:
            problematic_node = self._get_node_info(cycle_path[0], cycle_path[1])
            raise SubGraphValidationError(
                f"Recursion detected in node '{problematic_node['name']}'."
            )

    def _find_cycle(self, root_graph):
        """
        Detects cycles using DFS and returns the path if found.
        Returns list of [parent_graph_id, cyclic_subgraph_id] or None.
        """
        visited = set()
        stack = [(root_graph.id, [root_graph.id])]

        while stack:
            graph_id, path = stack.pop()

            if graph_id in visited:
                continue
            visited.add(graph_id)

            subgraphs = SubGraphNode.objects.filter(graph_id=graph_id).values_list(
                "subgraph_id", flat=True
            )

            for sub_id in subgraphs:
                if sub_id == root_graph.id:
                    return [graph_id, sub_id]
                if sub_id not in visited:
                    stack.append((sub_id, path + [sub_id]))

        return None

    def _get_node_info(self, parent_graph_id, subgraph_id):
        """
        Gets information about the SubGraphNode that creates the cycle.
        """
        node = (
            SubGraphNode.objects.filter(
                graph_id=parent_graph_id, subgraph_id=subgraph_id
            )
            .select_related("subgraph")
            .first()
        )

        return {
            "id": node.id if node else "Unknown",
            "name": (
                node.graph.name
                if node and node.graph.name
                else f'SubGraph Node {node.id if node else "Unknown"}'
            ),
            "subgraph_name": (
                node.subgraph.name if node and node.subgraph else "Unknown Flow"
            ),
        }
