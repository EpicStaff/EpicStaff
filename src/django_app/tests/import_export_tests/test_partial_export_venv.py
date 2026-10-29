"""A partially exported node carries the environment its python code runs in.

A full flow export collects environments from `GraphStrategy`, which a partial
export never walks: it starts at the node. Without the node strategies declaring
the dependency, the file would name a `venv` id it does not carry and the import
would refuse it.

The environment lives in the sandbox service, replaced here by the `sandbox` fixture.
"""

import json

import pytest

from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    ClassificationDecisionTableNode,
    PythonNode,
    WebhookTriggerNode,
)
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.import_export_tests.venv_fakes import upstream_venv

from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

FOREIGN_VENV_NAME = "BETA_ONLY_ENVIRONMENT"
FOREIGN_LIBRARY_NAME = "BETA_ONLY_LIBRARY"


def _code(venv):
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main", venv=venv)


def _python_node(graph, venv):
    return PythonNode.objects.create(graph=graph, node_name="py", python_code=_code(venv))


def _webhook_trigger_node(graph, venv):
    return WebhookTriggerNode.objects.create(
        graph=graph, node_name="hook", python_code=_code(venv)
    )


def _cdt_node_pre(graph, venv):
    return ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt", pre_python_code=_code(venv)
    )


def _cdt_node_post(graph, venv):
    return ClassificationDecisionTableNode.objects.create(
        graph=graph, node_name="cdt", post_python_code=_code(venv)
    )


# Every node type whose own python code can name an environment.
NODE_TYPES = [
    pytest.param(EntityType.PYTHON_NODE, _python_node, id="python-node"),
    pytest.param(EntityType.WEBHOOK_TRIGGER_NODE, _webhook_trigger_node, id="webhook-trigger-node"),
    pytest.param(
        EntityType.CLASSIFICATION_DECISION_TABLE_NODE, _cdt_node_pre, id="cdt-node-pre-code"
    ),
    pytest.param(
        EntityType.CLASSIFICATION_DECISION_TABLE_NODE, _cdt_node_post, id="cdt-node-post-code"
    ),
]


@pytest.fixture
def acme_graph(acme):
    return Graph.objects.create(name="acme-flow", org=acme)


def export_node(entity_type, node, org):
    return GraphPartialExportService(entity_registry).export(
        [NodeRef(entity_type, node.id)],
        org_id=org.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )


@pytest.mark.django_db
@pytest.mark.parametrize(("entity_type", "make_node"), NODE_TYPES)
def test_the_environment_the_node_runs_in_travels_with_it(
    acme, acme_graph, sandbox, entity_type, make_node
):
    binding = upstream_venv(sandbox, acme, venv_id=4711)

    result = export_node(entity_type, make_node(acme_graph, binding), acme)

    assert not result.has_errors
    [venv] = result.data[EntityType.VENV]
    # Addressed by the binding pk, which is what the node's `venv` field carries
    # and what the importing system remaps.
    assert venv["id"] == binding.pk
    assert venv["name"] == "scraper-venv"
    assert venv["libs"] == [{"name": "httpx", "specification": ">=0.28"}]


@pytest.mark.django_db
@pytest.mark.parametrize(("entity_type", "make_node"), NODE_TYPES)
def test_a_node_on_the_default_environment_carries_none(
    acme, acme_graph, sandbox, entity_type, make_node
):
    result = export_node(entity_type, make_node(acme_graph, None), acme)

    assert not result.has_errors
    assert result.data.get(EntityType.VENV, []) == []


@pytest.mark.django_db
@pytest.mark.parametrize(("entity_type", "make_node"), NODE_TYPES)
def test_an_environment_of_another_organization_stays_out(
    acme, beta, acme_graph, sandbox, entity_type, make_node
):
    """`PythonCode` carries no org of its own, so a node of this org can end up
    pointing at another tenant's environment. Its name and libraries must not reach
    the file, and no entry may claim an id the importer would then remap."""
    foreign = upstream_venv(
        sandbox,
        beta,
        name=FOREIGN_VENV_NAME,
        libs=[{"name": FOREIGN_LIBRARY_NAME, "specification": ">=1.0"}],
        venv_id=4712,
    )

    result = export_node(entity_type, make_node(acme_graph, foreign), acme)

    assert result.data.get(EntityType.VENV, []) == []
    serialized = json.dumps(result.data, default=str)
    assert FOREIGN_VENV_NAME not in serialized
    assert FOREIGN_LIBRARY_NAME not in serialized


@pytest.mark.django_db
def test_both_environments_of_a_classification_node_travel_with_it(acme, acme_graph, sandbox):
    pre_binding = upstream_venv(sandbox, acme, name="pre-venv", venv_id=4711)
    post_binding = upstream_venv(sandbox, acme, name="post-venv", venv_id=4712)
    node = ClassificationDecisionTableNode.objects.create(
        graph=acme_graph,
        node_name="cdt",
        pre_python_code=_code(pre_binding),
        post_python_code=_code(post_binding),
    )

    result = export_node(EntityType.CLASSIFICATION_DECISION_TABLE_NODE, node, acme)

    assert {venv["name"] for venv in result.data[EntityType.VENV]} == {"pre-venv", "post-venv"}


@pytest.mark.django_db
def test_two_nodes_sharing_an_environment_export_it_once(acme, acme_graph, sandbox):
    binding = upstream_venv(sandbox, acme, venv_id=4711)
    first, second = _python_node(acme_graph, binding), _python_node(acme_graph, binding)

    result = GraphPartialExportService(entity_registry).export(
        [
            NodeRef(EntityType.PYTHON_NODE, first.id),
            NodeRef(EntityType.PYTHON_NODE, second.id),
        ],
        org_id=acme.id,
        policy=UNRESTRICTED_EXPORT_POLICY,
    )

    assert [venv["id"] for venv in result.data[EntityType.VENV]] == [binding.pk]
