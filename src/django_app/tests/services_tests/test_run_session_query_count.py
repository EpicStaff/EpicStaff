"""Query budget for building and publishing one session.

`run_session` sits on the session-start path, so every query it repeats adds
latency before the flow begins. The graph below is representative: a start
node with its edge, two Python nodes declaring a secret (one with storage)
and a subgraph node whose subgraph has its own start node.
"""

import itertools

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rbac.models import Organization
from storage_credentials.services.org_credential_store import org_credential_store
from storage_credentials.services.session_credential_service import session_credential_service
from tables.models import Graph, PythonCode, Session
from tables.models.graph_models import (
    Edge,
    PythonNode,
    StartNode,
    SubGraphNode,
    WebhookTriggerNode,
)
from tables.services.secrets import secret_service
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec

SECRET_NAME = "query-count-key"

# Exact budget for representative_graph. If a change raises it, find the new
# query; if it lowers it, update the number.
RUN_SESSION_QUERY_COUNT = 62


def _python_node(graph: Graph, node_name: str, secret=None, use_storage=False) -> PythonNode:
    if secret is None:
        code = "def main(**kwargs):\n    return 1\n"
    else:
        code = f'def main(**kwargs):\n    return get_secret("{SECRET_NAME}") is not None\n'
    python_code = PythonCode.objects.create(code=code, entrypoint="main")
    if secret is not None:
        python_code.secrets.set([secret])
    return PythonNode.objects.create(
        graph=graph, python_code=python_code, node_name=node_name, use_storage=use_storage
    )


def _webhook_trigger_node(graph: Graph, node_name: str) -> WebhookTriggerNode:
    python_code = PythonCode.objects.create(code="def main(**kwargs):\n    return 1\n", entrypoint="main")
    return WebhookTriggerNode.objects.create(graph=graph, python_code=python_code, node_name=node_name)


@pytest.fixture
def org(db, monkeypatch):
    org = Organization.objects.create(name="Org RunSessionQueryCount")
    # The storage-using node makes run_session issue session credentials. Only the
    # storage backend call is faked; the credential lookup and the account row it
    # persists stay real, so their queries count toward the budget.
    org_credential_store.save(org=org, access_key="org-access", secret_key="org-secret")

    # Access keys are unique per stored account, so a test running twice needs a
    # fresh key each time.
    account_numbers = itertools.count()

    async def mint_temporary_service_account(org_creds, policy, expiration):
        return f"temporary-access-{next(account_numbers)}", "temporary-secret"

    monkeypatch.setattr(
        session_credential_service,
        "_mint_temporary_service_account",
        mint_temporary_service_account,
    )
    return org


@pytest.fixture
def secret(org):
    return secret_service.create(text="value", org=org, name=SECRET_NAME)


@pytest.fixture
def subgraph(org):
    subgraph = Graph.objects.create(name="query-count-subgraph", org=org)
    subgraph_start = StartNode.objects.create(graph=subgraph, variables={"inner": 1})
    subgraph_python = _python_node(subgraph, "inner_python")
    Edge.objects.create(
        graph=subgraph, start_node_id=subgraph_start.pk, end_node_id=subgraph_python.pk
    )
    return subgraph


@pytest.fixture
def representative_graph(org, secret, subgraph):
    graph = Graph.objects.create(
        name="query-count-graph", org=org, metadata={"nodes": [{"canvas": "x" * 1000}]}
    )
    start = StartNode.objects.create(graph=graph, variables={"variables": {}})
    first_python = _python_node(graph, "first_python", secret=secret)
    second_python = _python_node(graph, "second_python", secret=secret, use_storage=True)
    subgraph_node = SubGraphNode.objects.create(
        graph=graph, subgraph=subgraph, node_name="nested_flow"
    )
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=first_python.pk)
    Edge.objects.create(graph=graph, start_node_id=first_python.pk, end_node_id=second_python.pk)
    Edge.objects.create(graph=graph, start_node_id=second_python.pk, end_node_id=subgraph_node.pk)
    return graph


@pytest.fixture
def published(monkeypatch):
    published = []
    # Crew is the only subscriber; the Redis round-trip is not under test.
    monkeypatch.setattr(
        SessionManagerService().redis_service,
        "publish_session_data",
        lambda *, session_data, org_id, storage_credentials=None: (
            published.append((session_data, org_id)) or 1
        ),
    )
    return published


def _run(graph: Graph) -> int:
    return SessionManagerService().run_session(
        graph_id=graph.pk, variables={}, trigger=TriggerSpec.manual()
    )


@pytest.mark.django_db
def test_run_session_stays_within_query_budget(
    representative_graph, published, django_assert_num_queries
):
    with django_assert_num_queries(RUN_SESSION_QUERY_COUNT):
        _run(representative_graph)

    assert len(published) == 1


@pytest.mark.django_db
def test_another_secret_declaring_python_node_adds_no_queries(
    representative_graph, secret, published, django_assert_num_queries
):
    _python_node(representative_graph, "third_python", secret=secret)

    with django_assert_num_queries(RUN_SESSION_QUERY_COUNT):
        _run(representative_graph)


@pytest.mark.django_db
def test_payload_carries_org_and_secrets_read_from_the_graph_rows(
    representative_graph, subgraph, published
):
    session_id = _run(representative_graph)

    [(session_data, published_org_id)] = published
    org_id = representative_graph.org_id
    assert published_org_id == org_id
    assert session_data.org_id == org_id

    python_nodes = {
        node.node_name.split(" #")[0]: node.python_code
        for node in session_data.graph.python_node_list
    }
    assert python_nodes.keys() == {"first_python", "second_python"}
    for python_code in python_nodes.values():
        assert python_code.org_id == org_id
        assert python_code.secret_names == [SECRET_NAME]
    assert python_nodes["first_python"].storage_org_prefix is None
    assert python_nodes["second_python"].storage_org_prefix == f"org_{org_id}"
    assert python_nodes["second_python"].storage_allowed_paths == [f"sessions/{session_id}/"]

    [subgraph_data] = session_data.unique_subgraph_list
    assert subgraph_data.id == subgraph.pk
    assert subgraph_data.initial_state == {"inner": 1}
    [inner_python] = subgraph_data.data.python_node_list
    assert inner_python.python_code.org_id == subgraph.org_id
    assert inner_python.python_code.secret_names == []

    assert Session.objects.get(pk=session_id).status == Session.SessionStatus.PENDING


@pytest.mark.django_db
def test_another_webhook_trigger_node_adds_no_queries(
    representative_graph, published, django_assert_num_queries
):
    _webhook_trigger_node(representative_graph, "first_webhook")
    with CaptureQueriesContext(connection) as one_webhook_trigger_node:
        _run(representative_graph)

    _webhook_trigger_node(representative_graph, "second_webhook")

    with django_assert_num_queries(len(one_webhook_trigger_node.captured_queries)):
        _run(representative_graph)

    [_, (session_data, _)] = published
    assert {
        node.python_code.org_id for node in session_data.graph.webhook_trigger_node_data_list
    } == {representative_graph.org_id}
