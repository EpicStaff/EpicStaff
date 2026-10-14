"""A node's `execution_timeout` reaches every copy of the node and the session that
runs it.

Invariant: copying a graph, restoring a saved version of it, and building the
session schema crew runs all carry the node's own timeout (in minutes), never the
default. A copy or session that silently fell back to the ceiling would let user
code run longer than the designer allowed.
"""

import pytest

from rbac.models import Organization
from tables.graph_versioning.services import GraphVersioningService
from tables.models import Edge, Graph, StartNode
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tables.services.session_manager_service import SessionManagerService
from tests.execution_timeout_node_specs import (
    EXECUTION_TIMEOUT_NODE_SPEC_IDS,
    EXECUTION_TIMEOUT_NODE_SPECS,
)

# Distinct from any ceiling a test environment is likely to configure, so a path
# that drops the value and falls back to the default fails.
STORED_MINUTES = 3


@pytest.fixture(params=EXECUTION_TIMEOUT_NODE_SPECS, ids=EXECUTION_TIMEOUT_NODE_SPEC_IDS)
def spec(request):
    return request.param


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Org node execution timeout propagation")


@pytest.fixture
def graph(org):
    return Graph.objects.create(name="execution-timeout-propagation", org=org)


@pytest.fixture
def node(spec, graph, settings):
    settings.SANDBOX_MAX_EXECUTION_TIMEOUT_MINUTES = STORED_MINUTES + 10
    return spec.create(graph, execution_timeout=STORED_MINUTES)


@pytest.mark.django_db
def test_graph_copy_keeps_the_execution_timeout(spec, graph, node):
    copied_graph = GraphCopyService().copy(graph, name="copied")

    copied_node = getattr(copied_graph, spec.graph_list_key).get()
    assert copied_node.pk != node.pk
    assert copied_node.execution_timeout == STORED_MINUTES


@pytest.mark.django_db
def test_version_restore_brings_back_the_execution_timeout(spec, graph, node, regular_user):
    versioning = GraphVersioningService()
    version = versioning.save_version(graph=graph, name="with-timeout")
    spec.model.objects.filter(pk=node.pk).update(execution_timeout=STORED_MINUTES + 1)
    graph.refresh_from_db()

    versioning.restore_version(version, expected_save_version=graph.save_version, user=regular_user)

    assert getattr(graph, spec.graph_list_key).get().execution_timeout == STORED_MINUTES


@pytest.mark.django_db
def test_session_schema_carries_the_execution_timeout(spec, graph, node):
    # _build_graph_data needs a resolvable entrypoint; wire start -> node.
    start_node = StartNode.objects.create(graph=graph, variables={})
    Edge.objects.create(graph=graph, start_node_id=start_node.id, end_node_id=node.id)

    graph_data = SessionManagerService()._build_graph_data(graph, None, None)

    [node_data] = getattr(graph_data, spec.session_list_key)
    assert node_data.execution_timeout == STORED_MINUTES
