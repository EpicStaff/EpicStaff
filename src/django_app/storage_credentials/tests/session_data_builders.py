"""Minimal `SessionData` payloads carrying storage-demanding python nodes, for tests that
drive `session_credential_service.issue_for_session`."""

from src.shared.models.graph_nodes import EndNodeData, GraphData, PythonNodeData
from src.shared.models.sessions import SessionData
from src.shared.models.tools import PythonCodeData


def make_graph(python_node_list: list[PythonNodeData] | None = None) -> GraphData:
    """A minimal valid GraphData, optionally carrying python nodes."""
    return GraphData(
        graph_id=1,
        name="test_graph",
        entrypoint="start",
        end_node=EndNodeData(node_name="end", output_map={}),
        python_node_list=python_node_list or [],
    )


def make_storage_python_node(
    node_name: str = "storage_python",
    storage_allowed_paths: list[str] | None = None,
    storage_org_prefix: str = "org_123",
    org_id: int | None = None,
) -> PythonNodeData:
    """A python node whose code demands storage access."""
    return PythonNodeData(
        node_name=node_name,
        python_code=PythonCodeData(
            venv_name="test",
            code="x = 1",
            entrypoint="main",
            libraries=[],
            use_storage=True,
            storage_allowed_paths=storage_allowed_paths or ["test_path/"],
            storage_org_prefix=storage_org_prefix,
            org_id=org_id,
        ),
        input_map={},
    )


def make_session_data(session_id: int, graph: GraphData) -> SessionData:
    return SessionData(id=session_id, org_id=1, audit_retention_days=0, graph=graph, unique_subgraph_list=[])
