"""Collector for storage access requirements across a session graph.

Performs a recursive traversal of SessionData and its subgraphs to identify
all nodes that require storage access (use_storage=True) and aggregates their
scope information.
"""

from pydantic import BaseModel
from src.shared.models.graph_nodes import (
    GraphData,
)
from src.shared.models.sessions import SessionData
from src.shared.models.storage_scope import StorageScopedData
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
    collector = _StorageDemandWalker()

    collector.visit_graph(session_data.graph)

    for subgraph in session_data.unique_subgraph_list:
        collector.visit_graph(subgraph.data)

    return (
        collector.needs_storage,
        list(collector.union_paths),
        collector.org_prefix,
    )


class _StorageDemandWalker:
    """Internal state tracker for recursive graph traversal."""

    def __init__(self):
        self.needs_storage = False
        self.union_paths = set()
        self.org_prefix = None

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
            self._visit_tools(node.tools)

        for node in graph.task_node_list:
            self._visit_tools(node.tools)

        for edge in graph.conditional_edge_list:
            self._check_storage_scoped(edge.python_code)

    def _visit_tools(self, tools: list[BaseToolData]) -> None:
        """Traverse tools list to find PythonCodeData nodes."""
        for tool in tools:
            if isinstance(tool.data, PythonCodeToolData):
                self._check_storage_scoped(tool.data.python_code)

    def _check_storage_scoped(self, node: BaseModel) -> None:
        """Check if node is StorageScopedData with use_storage=True."""
        if not isinstance(node, StorageScopedData):
            return

        if not node.use_storage:
            return

        self.needs_storage = True

        if node.storage_allowed_paths:
            self.union_paths.update(node.storage_allowed_paths)

        if self.org_prefix is None and node.storage_org_prefix is not None:
            self.org_prefix = node.storage_org_prefix
