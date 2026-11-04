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
from src.shared.models.storage_scope import StorageGrant, StorageScopedData
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
    """Which storage grants the storage-using nodes and code slots of a session carry.

    Attributes:
        grants: Every distinct grant among them.
        has_ungranted: Whether some storage-using node or slot has no grant at all.
    """

    grants: frozenset[StorageGrant] = field(default_factory=frozenset)
    has_ungranted: bool = False


def collect_storage_grant_demand(session_data: SessionData) -> StorageGrantDemand:
    """Traverse the session graph and its subgraphs for the grants of their storage-using code.

    A python node, webhook trigger, classification decision table slot, file extractor or
    audio transcription node counts through its own grant; an agent or task node counts
    once through its grant for all of its python tools that use storage.
    """
    collector = _walk(session_data)
    return StorageGrantDemand(
        grants=frozenset(collector.grants), has_ungranted=collector.has_ungranted
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
        self.grants: set[StorageGrant] = set()
        self.has_ungranted = False

    def visit_graph(self, graph: GraphData) -> None:
        """Traverse all node lists in a graph."""
        for node in graph.webhook_trigger_node_data_list:
            self._check_storage_scoped(node.python_code)

        for node in graph.python_node_list:
            self._check_storage_scoped(node.python_code)

        for node in graph.file_extractor_node_list:
            self._check_storage_scoped(node)

        for node in graph.audio_transcription_node_list:
            self._check_storage_scoped(node)

        for node in graph.classification_decision_table_node_list:
            if node.pre_python_code:
                self._check_storage_scoped(node.pre_python_code)
            if node.post_python_code:
                self._check_storage_scoped(node.post_python_code)

        for node in graph.agent_node_list:
            self._visit_tools(node.tools, node.storage_grant)

        for node in graph.task_node_list:
            self._visit_tools(node.tools, node.storage_grant)

    def _visit_tools(self, tools: list[BaseToolData], grant: StorageGrant | None) -> None:
        """Traverse tools list to find PythonCodeData nodes; they run with the owning node's grant."""
        for tool in tools:
            if isinstance(tool.data, PythonCodeToolData):
                self._check_storage_scoped(tool.data.python_code, grant)

    def _check_storage_scoped(self, node: BaseModel, grant: StorageGrant | None = None) -> None:
        """Check if node is StorageScopedData with use_storage=True."""
        if not isinstance(node, StorageScopedData):
            return

        if not node.use_storage:
            return

        self.needs_storage = True

        effective_grant = grant if grant is not None else node.storage_grant
        if effective_grant is None:
            self.has_ungranted = True
        else:
            self.grants.add(effective_grant)

        if node.storage_allowed_paths:
            self.union_paths.update(node.storage_allowed_paths)

        if self.org_prefix is None and node.storage_org_prefix is not None:
            self.org_prefix = node.storage_org_prefix
