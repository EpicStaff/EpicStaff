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
                f"Recursion detected: '{problematic_node['parent_graph_name']}' references "
                f"'{problematic_node['subgraph_name']}' which creates a cycle."
            )

    def _find_cycle(self, root_graph):
        """
        Detects cycles using iterative DFS.
        Returns list of [parent_graph_id, cyclic_subgraph_id] or None.
        Detects all cycles: self-loops, cycles through root, and cycles between intermediates.
        """
        # Stack contains tuples: (parent_graph_id, graph_id, is_exit_marker)
        # is_exit_marker=True means this is a cleanup marker (pop from on_path when encountered)
        stack = [(None, root_graph.id, False)]
        on_path = set()  # Gray nodes: currently being explored
        completed = set()  # Black nodes: fully explored

        while stack:
            parent_graph_id, graph_id, is_exit_marker = stack.pop()

            if is_exit_marker:
                # Cleanup marker: remove from on_path and mark as completed
                on_path.discard(graph_id)
                completed.add(graph_id)
                continue

            # Cycle detected: we're revisiting a node that's currently on the path
            if graph_id in on_path:
                return [parent_graph_id, graph_id]

            # Skip if already fully explored
            if graph_id in completed:
                continue

            # Mark as being explored (gray node)
            on_path.add(graph_id)

            # Push exit marker before pushing children
            # This ensures on_path is cleaned up after all children are processed
            stack.append((graph_id, graph_id, True))

            # Query subgraph references from this graph
            subgraphs = SubGraphNode.objects.filter(graph_id=graph_id).values_list(
                "subgraph_id", flat=True
            )

            # Push children onto stack (reversed to maintain left-to-right order)
            for sub_id in reversed(list(subgraphs)):
                if sub_id is not None:  # Skip nullable subgraph fields
                    stack.append((graph_id, sub_id, False))

        return None

    def _get_node_info(self, parent_graph_id, subgraph_id):
        """
        Gets information about the SubGraphNode that creates the cycle.
        Returns dict with parent and subgraph names to clearly identify the cycle.
        """
        node = (
            SubGraphNode.objects.filter(graph_id=parent_graph_id, subgraph_id=subgraph_id)
            .select_related("subgraph", "graph")
            .first()
        )

        parent_graph = Graph.objects.filter(id=parent_graph_id).first() if not node else node.graph

        return {
            "id": node.id if node else "Unknown",
            "parent_graph_name": parent_graph.name if parent_graph else f"Flow {parent_graph_id}",
            "subgraph_name": (
                node.subgraph.name if node and node.subgraph else f"Flow {subgraph_id}"
            ),
        }
