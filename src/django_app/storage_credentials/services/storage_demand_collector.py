"""Collector for storage access requirements across a session graph.

Performs a recursive traversal of SessionData and its subgraphs to identify
all nodes that require storage access (use_storage=True) and aggregates their
scope information.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel
from src.shared.models.graph_nodes import (
    GraphData,
)
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import (
    FILE_NODE_STORAGE_GRANT,
    StorageGrant,
    StorageScopedData,
    storage_account_key,
)
from src.shared.models.tools import BaseToolData, PythonCodeToolData


def collect_storage_demand(session_data: SessionData) -> tuple[bool, list[str], str | None]:
    """Traverse SessionData graph and subgraphs to find storage requirements.

    Performs a generic recursive walk similar to SecretResolver._fill(), searching for
    all nodes with StorageScopedData.use_storage=True. Aggregates scope information
    across all matching nodes.

    Args:
        session_data: The session containing the graph and subgraphs.

    Returns:
        Tuple of:
        - needs_storage (bool): True if any node requires storage access.
        - union_allowed_paths (list[str]): Union of storage_allowed_paths from all
          storage-demanding nodes. Empty list if needs_storage is False.
        - org_prefix (str | None): First found storage_org_prefix, or None if not set.
          All nodes in a session share the same org context.
    """
    collector = _walk(session_data)

    return (
        collector.needs_storage,
        list(collector.union_paths),
        collector.org_prefix,
    )


@dataclass(frozen=True)
class StorageGrantDemand:
    """The storage accounts the storage-using code of a session calls for.

    Attributes:
        accounts: By `storage_account_key`, each grant used in a flow with the allowed
            paths of that flow's nodes. A grant used in two flows is two entries, so an
            account never reaches files attached to another flow.
        has_ungranted: Whether some storage-using code has no grant (the python tools of
            agent and task nodes), and so runs with the default account.
        ungranted_paths: The allowed paths of that code; empty without it.
    """

    accounts: dict[str, tuple[StorageGrant, frozenset[str]]] = field(default_factory=dict)
    has_ungranted: bool = False
    ungranted_paths: frozenset[str] = frozenset()


def collect_storage_grant_demand(session_data: SessionData) -> StorageGrantDemand:
    """Traverse the session graph and its subgraphs for the accounts their storage-using code needs.

    A python node, webhook trigger or classification decision table slot counts through its
    own grant; a file extractor or audio transcription node through the fixed read-only
    `FILE_NODE_STORAGE_GRANT`. Each is recorded under its own flow's id, sub-flows
    included, with that flow's `storage_allowed_paths`. The python tools of agent and task
    nodes carry no grant and count as ungranted.
    """
    collector = _walk(session_data)
    return StorageGrantDemand(
        accounts={
            key: (grant, frozenset(paths)) for key, (grant, paths) in collector.accounts.items()
        },
        has_ungranted=collector.has_ungranted,
        ungranted_paths=frozenset(collector.ungranted_paths),
    )


def _walk(session_data: SessionData) -> "_StorageDemandWalker":
    collector = _StorageDemandWalker()
    collector.visit_graph(session_data.graph)
    for subgraph in session_data.unique_subgraph_list:
        collector.visit_graph(subgraph.data)
    return collector


class _StorageDemandWalker:
    """Internal state tracker for recursive graph traversal."""

    def __init__(self):
        self.needs_storage = False
        self.union_paths = set()
        self.org_prefix = None
        self.accounts: dict[str, tuple[StorageGrant, set[str]]] = {}
        self.has_ungranted = False
        self.ungranted_paths: set[str] = set()

    def visit_graph(self, graph: GraphData) -> None:
        """Traverse all node lists in a graph."""
        for node in graph.webhook_trigger_node_data_list:
            self._check_storage_scoped(node.python_code, graph.graph_id)

        for node in graph.python_node_list:
            self._check_storage_scoped(node.python_code, graph.graph_id)

        for node in graph.file_extractor_node_list:
            self._check_storage_scoped(node, graph.graph_id, FILE_NODE_STORAGE_GRANT)

        for node in graph.audio_transcription_node_list:
            self._check_storage_scoped(node, graph.graph_id, FILE_NODE_STORAGE_GRANT)

        for node in graph.classification_decision_table_node_list:
            if node.pre_python_code:
                self._check_storage_scoped(node.pre_python_code, graph.graph_id)
            if node.post_python_code:
                self._check_storage_scoped(node.post_python_code, graph.graph_id)

        for node in graph.agent_node_list:
            self._visit_tools(node.tools, graph.graph_id)

        for node in graph.task_node_list:
            self._visit_tools(node.tools, graph.graph_id)

    def _visit_tools(self, tools: list[BaseToolData], graph_id: int | None) -> None:
        """Traverse tools list to find PythonCodeData nodes; they carry no grant."""
        for tool in tools:
            if isinstance(tool.data, PythonCodeToolData):
                self._check_storage_scoped(tool.data.python_code, graph_id)

    def _check_storage_scoped(
        self, node: BaseModel, graph_id: int | None, grant: StorageGrant | None = None
    ) -> None:
        """Record `node` if it is StorageScopedData with use_storage=True.

        `grant` is the fixed grant of a node that has no grant of its own; otherwise the
        node's own grant counts, and none means ungranted tool code.
        """
        if not isinstance(node, StorageScopedData):
            return

        if not node.use_storage:
            return

        self.needs_storage = True

        effective_grant = grant if grant is not None else node.storage_grant
        node_paths = set(node.storage_allowed_paths or [])
        if effective_grant is None:
            self.has_ungranted = True
            self.ungranted_paths.update(node_paths)
        else:
            _, paths = self.accounts.setdefault(
                storage_account_key(effective_grant, graph_id), (effective_grant, set())
            )
            paths.update(node_paths)

        if node.storage_allowed_paths:
            self.union_paths.update(node.storage_allowed_paths)

        if self.org_prefix is None and node.storage_org_prefix is not None:
            self.org_prefix = node.storage_org_prefix
