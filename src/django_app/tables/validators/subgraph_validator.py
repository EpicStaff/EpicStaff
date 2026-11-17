from dataclasses import dataclass

from utils.graph_utils import node_label

from tables.exceptions import SubGraphValidationError
from tables.models import Graph, SubGraphNode


@dataclass(frozen=True)
class _Visit:
    """One step of the walk: entering `graph_id` through `via` (None for the flow that was run)."""

    graph_id: int
    via: SubGraphNode | None
    # The Subflow node in the flow that was run that this path started from.
    entry: SubGraphNode | None
    is_exit_marker: bool = False


class SubGraphValidator:
    """
    Validates that every Subflow node a run reaches has a flow, and that no flows run
    each other in a loop.
    """

    def validate(self, graph: Graph):
        """
        Walks the flows the run reaches through Subflow nodes, depth first.

        Raises:
            SubGraphValidationError: A Subflow node with no flow, or the first loop found.
                The error names the Subflow node the user can find: the one in the flow
                that was run, unless the node runs its own flow.
        """
        stack = [_Visit(graph_id=graph.id, via=None, entry=None)]
        on_path = set()  # Gray nodes: currently being explored
        completed = set()  # Black nodes: fully explored

        while stack:
            visit = stack.pop()

            if visit.is_exit_marker:
                on_path.discard(visit.graph_id)
                completed.add(visit.graph_id)
                continue

            if visit.graph_id in on_path:
                raise self._loop_error(visit, root_graph_id=graph.id)

            if visit.graph_id in completed:
                continue

            on_path.add(visit.graph_id)
            # Pushed before the children, so on_path is cleaned up after all of them.
            stack.append(_Visit(graph_id=visit.graph_id, via=None, entry=None, is_exit_marker=True))

            flow_name = None if visit.via is None else visit.via.subgraph.name
            subflow_nodes = list(
                SubGraphNode.objects.filter(graph_id=visit.graph_id).select_related("subgraph")
            )
            for subflow_node in subflow_nodes:
                if subflow_node.subgraph_id is None:
                    raise SubGraphValidationError.no_flow_selected(
                        node_label=self._label(subflow_node), flow_name=flow_name
                    )

            # Reversed to keep left-to-right order.
            for subflow_node in reversed(subflow_nodes):
                stack.append(
                    _Visit(
                        graph_id=subflow_node.subgraph_id,
                        via=subflow_node,
                        entry=visit.entry or subflow_node,
                    )
                )

    def _loop_error(self, visit: _Visit, *, root_graph_id: int) -> SubGraphValidationError:
        via = visit.via
        if via.graph_id == via.subgraph_id:
            return SubGraphValidationError.runs_own_flow(
                node_label=self._label(via),
                # The node runs the flow it sits in, so that flow is its subgraph.
                flow_name=None if via.graph_id == root_graph_id else via.subgraph.name,
            )
        if visit.graph_id == root_graph_id:
            return SubGraphValidationError.loop_through_run_flow(
                node_label=self._label(visit.entry), flow_name=visit.entry.subgraph.name
            )
        return SubGraphValidationError.leads_to_loop(
            node_label=self._label(visit.entry), flow_name=via.subgraph.name
        )

    @staticmethod
    def _label(subflow_node: SubGraphNode) -> str:
        return node_label(node_name=subflow_node.node_name, node_number=subflow_node.node_number)
