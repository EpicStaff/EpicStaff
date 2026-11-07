from utils.graph_utils import flow_location, node_label

from tables.exceptions import SubGraphValidationError
from tables.models import Graph, SubGraphNode
from tables.services.flow_reachability import nodes_reachable_from_start


class SubGraphValidator:
    """Refuses a run whose subflow nodes can't be built.

    A subflow node with no flow chosen has nothing to run, and a chain of subflows
    that comes back to a flow already on it would loop forever: building the session
    recurses into every subflow the run reaches. Only subflow nodes the run reaches
    are checked and followed; one the run never gets to is left out of the session.
    """

    def validate(self, graph: Graph, *, reachable_node_ids: set[int] | None) -> dict[int, set[int]]:
        """Walk every flow the run reaches through subflow nodes, depth first.

        A loop is reported through the subflow node in `graph` that leads into it,
        because that is the node the user sees on the canvas they ran, together
        with the flow where the loop closes.

        Args:
            reachable_node_ids: The nodes of `graph` the run reaches, or None to check
                every subflow node of `graph`. In a subflow, the nodes reached from its
                Start node are checked.

        Returns:
            The ids of the nodes each subflow's run reaches, by flow id, for every
            subflow the run reaches; the session builder sends exactly those.

        Raises:
            SubGraphValidationError: A subflow node has no flow chosen, or a chain of
                subflows runs a flow that is already on it.
        """
        reachable_node_ids_by_subflow: dict[int, set[int]] = {}
        self._visit(
            graph_id=graph.id,
            reachable_node_ids=reachable_node_ids,
            entry_node=None,
            root_graph=graph,
            flows_on_path=set(),
            finished_flow_ids=set(),
            reachable_node_ids_by_subflow=reachable_node_ids_by_subflow,
        )
        return reachable_node_ids_by_subflow

    def _visit(
        self,
        *,
        graph_id: int,
        reachable_node_ids: set[int] | None,
        entry_node: SubGraphNode | None,
        root_graph: Graph,
        flows_on_path: set[int],
        finished_flow_ids: set[int],
        reachable_node_ids_by_subflow: dict[int, set[int]],
    ) -> None:
        # Recursion depth is the subflow nesting depth, which _build_graph_data
        # recurses through as well.
        flows_on_path.add(graph_id)
        subflow_nodes = (
            SubGraphNode.objects.filter(graph_id=graph_id)
            .select_related("graph", "subgraph")
            .only("node_name", "node_number", "graph__name", "subgraph__name")
            .order_by("node_number", "id")
        )
        for subflow_node in subflow_nodes:
            if reachable_node_ids is not None and subflow_node.id not in reachable_node_ids:
                continue
            if subflow_node.subgraph_id is None:
                raise SubGraphValidationError(self._no_flow_message(subflow_node, root_graph))

            path_start = entry_node or subflow_node
            if subflow_node.subgraph_id in flows_on_path:
                raise SubGraphValidationError(
                    self._loop_message(path_start, subflow_node, root_graph)
                )
            if subflow_node.subgraph_id not in finished_flow_ids:
                subflow_reachable_node_ids = nodes_reachable_from_start(subflow_node.subgraph_id)
                reachable_node_ids_by_subflow[subflow_node.subgraph_id] = subflow_reachable_node_ids
                self._visit(
                    graph_id=subflow_node.subgraph_id,
                    reachable_node_ids=subflow_reachable_node_ids,
                    entry_node=path_start,
                    root_graph=root_graph,
                    flows_on_path=flows_on_path,
                    finished_flow_ids=finished_flow_ids,
                    reachable_node_ids_by_subflow=reachable_node_ids_by_subflow,
                )
        flows_on_path.remove(graph_id)
        finished_flow_ids.add(graph_id)

    @staticmethod
    def _no_flow_message(subflow_node: SubGraphNode, root_graph: Graph) -> str:
        name = node_label(node_name=subflow_node.node_name, node_number=subflow_node.node_number)
        location = flow_location(
            None if subflow_node.graph_id == root_graph.id else subflow_node.graph.name
        )
        return f'Subflow node "{name}"{location} has no flow selected.'

    @staticmethod
    def _loop_message(
        path_start: SubGraphNode, closing_node: SubGraphNode, root_graph: Graph
    ) -> str:
        """Describe a loop from the node on the root canvas that leads into it.

        `closing_node` is the subflow node that runs a flow already on the chain.
        """
        name = node_label(node_name=path_start.node_name, node_number=path_start.node_number)
        if closing_node.subgraph_id == root_graph.id:
            if path_start.subgraph_id == root_graph.id:
                return f'Subflow node "{name}" runs its own flow. Choose another flow.'
            return (
                f'Subflow node "{name}" makes a loop through flow "{path_start.subgraph.name}". '
                "Choose another flow."
            )
        # The loop closes further down the chain, in a flow the user didn't run, so
        # that's where they fix it, whether that flow runs itself or another one.
        return (
            f'Subflow node "{name}" leads to a loop in flow "{closing_node.graph.name}". '
            "Choose another flow there."
        )
