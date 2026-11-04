"""Which nodes of a flow a run reaches, following every route crew moves along.

Crew moves from one node to the next only along:

- an edge;
- a Decision Table node's routes: each condition's next node, the default next node
  and the error node;
- a Classification Table node's routes: each enabled row's next node, the default
  next node and the error node. Crew skips a disabled row (`dock_visible` off), so its
  next node is not a route.

A Subflow node runs its flow, then goes on along its edges like any other node.

NOTE: a new node type that picks its next node at run time must add its routes in
`FlowRoutes.from_rows`, or the nodes behind it are neither checked before a run nor
sent to crew.
"""

from collections import deque
from collections.abc import Iterable

from tables.models import Edge, StartNode
from tables.models.graph_models import ClassificationDecisionTableNode, DecisionTableNode


class FlowRoutes:
    """The routes out of each node of one flow, by node id."""

    def __init__(self, next_node_ids_by_node: dict[int, set[int]]):
        self._next_node_ids_by_node = next_node_ids_by_node

    @classmethod
    def from_rows(
        cls,
        *,
        edges: Iterable[Edge],
        decision_table_nodes: Iterable[DecisionTableNode],
        classification_decision_table_nodes: Iterable[ClassificationDecisionTableNode],
    ) -> "FlowRoutes":
        """Collect the routes of a flow from its loaded rows.

        Args:
            decision_table_nodes: Loaded with `condition_groups` prefetched, or each node
                costs a query. The prefetch leaves out conditions in the recycle bin,
                as the session data sent to crew does.
            classification_decision_table_nodes: Loaded with `condition_groups`
                prefetched, or each node costs a query.
        """
        next_node_ids_by_node: dict[int, set[int]] = {}

        def add_routes(node_id: int, next_node_ids: Iterable[int | None]) -> None:
            next_node_ids_by_node.setdefault(node_id, set()).update(
                next_node_id for next_node_id in next_node_ids if next_node_id is not None
            )

        for edge in edges:
            add_routes(edge.start_node_id, [edge.end_node_id])
        for node in decision_table_nodes:
            add_routes(
                node.id,
                [
                    node.default_next_node_id,
                    node.next_error_node_id,
                    *(group.next_node_id for group in node.condition_groups.all()),
                ],
            )
        for node in classification_decision_table_nodes:
            add_routes(
                node.id,
                [
                    node.default_next_node_id,
                    node.next_error_node_id,
                    *(
                        group.next_node_id
                        for group in node.condition_groups.all()
                        if group.dock_visible
                    ),
                ],
            )
        return cls(next_node_ids_by_node)

    @classmethod
    def load(cls, graph_id: int) -> "FlowRoutes":
        """Load the routes of a flow whose rows aren't loaded yet. Costs five queries."""
        return cls.from_rows(
            edges=Edge.objects.filter(graph_id=graph_id).only("start_node_id", "end_node_id"),
            decision_table_nodes=DecisionTableNode.objects.filter(graph_id=graph_id)
            .only("id", "default_next_node_id", "next_error_node_id")
            .prefetch_related("condition_groups"),
            classification_decision_table_nodes=ClassificationDecisionTableNode.objects.filter(
                graph_id=graph_id
            )
            .only("id", "default_next_node_id", "next_error_node_id")
            .prefetch_related("condition_groups"),
        )

    def reachable_from(self, entry_node_ids: Iterable[int]) -> set[int]:
        """Return the ids of the entry nodes and every node a route leads to from them."""
        reachable = set(entry_node_ids)
        pending = deque(reachable)
        while pending:
            for next_node_id in self._next_node_ids_by_node.get(pending.popleft(), ()):
                if next_node_id not in reachable:
                    reachable.add(next_node_id)
                    pending.append(next_node_id)
        return reachable


def nodes_reachable_by_run(
    *,
    routes: FlowRoutes,
    node_names: dict[int, str],
    entrypoint: str | None,
    start_node_id: int | None,
) -> set[int] | None:
    """Return the ids of the nodes a run reaches, or None to treat every node as reached.

    A run starts where crew starts it: at the node a trigger names (`entrypoint`, a
    runtime name), otherwise at the Start node. Every edge out of Start counts, though
    crew takes only one of them, so no node it might start at goes unchecked.

    Args:
        node_names: The runtime name of each node of the flow, by id; searched for
            `entrypoint`.
        entrypoint: The runtime name of the node a trigger started the run at; None
            for a run that starts at Start, as every subflow does.

    Returns:
        None when no node has the trigger's name: where crew starts is then unknown,
        so every node is checked and sent. An empty set when the run has no Start node.
    """
    if entrypoint is not None:
        entry_node_ids = [
            node_id for node_id, node_name in node_names.items() if node_name == entrypoint
        ]
        if not entry_node_ids:
            return None
        return routes.reachable_from(entry_node_ids)
    return reachable_from_start(routes, start_node_id)


def reachable_from_start(routes: FlowRoutes, start_node_id: int | None) -> set[int]:
    """Return the ids of the nodes a run reaches from Start; empty without a Start node."""
    if start_node_id is None:
        return set()
    return routes.reachable_from([start_node_id])


def nodes_reachable_from_start(graph_id: int) -> set[int]:
    """Return the ids of the nodes a run of a subflow reaches from its Start node.

    The Start node is the one the session builder takes for a subflow (the first), so
    this matches the entrypoint crew is sent. Empty when the flow has no Start node.
    Costs six queries.
    """
    start_node = StartNode.objects.filter(graph_id=graph_id).only("id").first()
    return reachable_from_start(FlowRoutes.load(graph_id), start_node.id if start_node else None)
