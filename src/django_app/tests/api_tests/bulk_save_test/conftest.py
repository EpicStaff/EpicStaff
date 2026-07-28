import pytest

from tables.models.graph_models import (
    CrewNode,
    DecisionTableNode,
    Edge,
    PythonNode,
)


@pytest.fixture
def auth_client(api_client, regular_user, default_org):
    """Override the global `auth_client` for bulk_save tests.

    Bulk-save's post-save `notify_graph_saved` broadcast (and the RBAC gate
    in front of it) needs `request.user` set to a real user, but test
    settings clear `DEFAULT_AUTHENTICATION_CLASSES` so the JWT Bearer header
    from the global `auth_client` is never processed and `request.user`
    stays `AnonymousUser` (same gap `tests/graph_collab/conftest.py`
    documents and works around). `force_authenticate` bypasses
    authentication entirely. `regular_user` is an Org Admin member of
    `default_org`, matching the shared `graph` fixture (`fixtures.py`),
    which is created in `default_org` — so the active-org header resolves
    to the graph's own org.
    """
    api_client.force_authenticate(user=regular_user)
    api_client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return api_client


@pytest.fixture
def python_node(graph, python_code) -> PythonNode:
    return PythonNode.objects.create(graph=graph, python_code=python_code)


@pytest.fixture
def crew_node(graph, crew) -> CrewNode:
    return CrewNode.objects.create(graph=graph, crew=crew)


@pytest.fixture
def decision_table_node(graph) -> DecisionTableNode:
    return DecisionTableNode.objects.create(graph=graph, node_name="dt_node_1")


@pytest.fixture
def edge(graph, python_node, crew_node) -> Edge:
    return Edge.objects.create(
        graph=graph,
        start_node_id=python_node.id,
        end_node_id=crew_node.id,
    )
