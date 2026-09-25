"""GET /graph-versions/<id>/preview/ — the read-only view of what a restore would apply."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import OrganizationUser, Role, RolePermission
from rbac.models.enums import Permission, ResourceType
from tables.graph_versioning.services import GraphVersioningService
from tables.models import GraphVersion, PythonCode, PythonNode
from tables.models.graph_models import Edge, Graph, SubGraphNode
from tests.api_tests.graph_version_api_fixtures import *  # noqa: F401,F403
from tests.api_tests.graph_version_api_fixtures import save_version
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


def _preview(*, client, version_id):
    return client.get(reverse("graph-versions-preview", args=[version_id]))


def _graph_with_python_nodes(*, org, name, node_count):
    graph = Graph.objects.create(name=name, org=org)
    for index in range(node_count):
        PythonNode.objects.create(
            graph=graph,
            node_name=f"Python-Node #{index + 1}",
            python_code=PythonCode.objects.create(code="def main():\n    return 1\n"),
        )
    return graph


@pytest.mark.django_db
def test_preview_returns_the_snapshot_and_secret_declaration(
    client, graph_with_declared_secret
):
    graph, _ = graph_with_declared_secret
    version_id = save_version(client=client, graph=graph)

    response = _preview(client=client, version_id=version_id)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["warnings"] == []
    snapshot = response.data["snapshot"]
    assert len(snapshot["nodes"]) == 1
    node_id = str(snapshot["nodes"][0]["id"])
    assert snapshot["secret_declarations"]["nodes"][node_id]["python_code"] == [
        "STRIPE_KEY"
    ]


@pytest.mark.django_db
def test_preview_never_persists_a_graph_or_python_node(
    client, graph_with_declared_secret
):
    """The entire point of /preview/: repeated calls must not create or consume
    any Graph/PythonNode/PythonCode row — unlike create-graph, which does."""
    graph, _ = graph_with_declared_secret
    version_id = save_version(client=client, graph=graph)

    graphs_before = Graph.objects.count()
    nodes_before = PythonNode.objects.count()
    codes_before = PythonCode.objects.count()

    for _ in range(3):
        response = _preview(client=client, version_id=version_id)
        assert response.status_code == status.HTTP_200_OK, response.content

    assert Graph.objects.count() == graphs_before
    assert PythonNode.objects.count() == nodes_before
    assert PythonCode.objects.count() == codes_before


@pytest.mark.django_db
def test_preview_nonexistent_version_returns_404(client):
    response = client.get(reverse("graph-versions-preview", args=[99999]))

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_preview_of_another_orgs_version_returns_404(
    client_as, admin_acme, acme, beta
):
    acme_version = GraphVersioningService().save_version(
        _graph_with_python_nodes(org=acme, name="acme-flow", node_count=1), name="acme"
    )
    beta_version = GraphVersioningService().save_version(
        _graph_with_python_nodes(org=beta, name="beta-flow", node_count=1), name="beta"
    )
    acme_client = client_as(admin_acme)
    acme_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    own_response = _preview(client=acme_client, version_id=acme_version.id)
    foreign_response = _preview(client=acme_client, version_id=beta_version.id)

    # Positive control: the same caller can preview its own org's version, so the
    # 404 below is the org filter and not a broken client.
    assert own_response.status_code == status.HTTP_200_OK, own_response.content
    assert foreign_response.status_code == status.HTTP_404_NOT_FOUND
    assert "snapshot" not in foreign_response.json()


@pytest.mark.django_db
def test_preview_without_flows_read_permission_returns_403(
    django_user_model, org, graph_with_declared_secret
):
    graph, _ = graph_with_declared_secret
    version = GraphVersioningService().save_version(graph, name="v1")
    role = Role.objects.create(name="role-no-flows", org=org, is_built_in=False)
    RolePermission.objects.create(
        role=role,
        resource_type=ResourceType.SECRETS.value,
        permissions=int(Permission.READ),
    )
    user = django_user_model.objects.create_user(
        email="no-flows-preview@example.com", password="StrongPass123!"
    )
    OrganizationUser.objects.create(user=user, org=org, role=role)
    no_flows_client = APIClient()
    no_flows_client.force_authenticate(user=user)
    no_flows_client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))

    response = _preview(client=no_flows_client, version_id=version.id)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert "snapshot" not in response.json()


@pytest.mark.django_db
def test_preview_nulls_the_reference_to_a_deleted_subflow_and_warns(client, org):
    """A missing dependency does not drop the node: its FK is nulled and reported,
    exactly as restore does."""
    subflow = Graph.objects.create(name="subflow", org=org)
    graph = Graph.objects.create(name="parent-flow", org=org)
    subgraph_node = SubGraphNode.objects.create(
        graph=graph, node_name="Subflow #1", subgraph=subflow
    )
    version_id = save_version(client=client, graph=graph)
    subflow_id = subflow.id
    subflow.delete()

    response = _preview(client=client, version_id=version_id)

    assert response.status_code == status.HTTP_200_OK, response.content
    [node] = response.data["snapshot"]["nodes"]
    assert node["id"] == subgraph_node.id
    assert node["subgraph"] is None
    [warning] = response.data["warnings"]
    assert warning["type"] == "fk_nulled"
    assert warning["missing_id"] == subflow_id


@pytest.mark.django_db
def test_preview_converts_a_legacy_snapshot_and_drops_unsupported_nodes_and_their_edges(
    client, org
):
    """A version saved before IMPORT_VERSION 3: the v2->v3 conversion strips
    PythonNode.stream_config, and a node type that no longer exists is removed
    together with every edge pointing at it."""
    graph = _graph_with_python_nodes(org=org, name="legacy-flow", node_count=1)
    python_node = graph.python_node_list.get()
    Edge.objects.create(graph=graph, start_node_id=python_node.id, end_node_id=python_node.id)
    version = GraphVersioningService().save_version(graph, name="legacy")

    legacy_snapshot = version.snapshot
    legacy_snapshot["version"] = 2
    [python_node_entry] = legacy_snapshot["nodes"]
    python_node_entry["stream_config"] = {"enabled": True}
    crew_node_id = python_node.id + 1000
    legacy_snapshot["nodes"].append(
        {"id": crew_node_id, "node_type": "CrewNode", "node_name": "Crew Node #1", "crew": 1}
    )
    legacy_snapshot["edge_list"].append(
        {"start_node_id": python_node.id, "end_node_id": crew_node_id}
    )
    GraphVersion.objects.filter(pk=version.pk).update(snapshot=legacy_snapshot)

    response = _preview(client=client, version_id=version.id)

    assert response.status_code == status.HTTP_200_OK, response.content
    snapshot = response.data["snapshot"]
    assert [node["id"] for node in snapshot["nodes"]] == [python_node.id]
    assert "stream_config" not in snapshot["nodes"][0]
    assert [(edge["start_node_id"], edge["end_node_id"]) for edge in snapshot["edge_list"]] == [
        (python_node.id, python_node.id)
    ]
    assert sorted(warning["type"] for warning in response.data["warnings"]) == [
        "edge_dropped",
        "node_type_unsupported",
    ]


@pytest.mark.django_db
def test_preview_nulls_plaintext_credentials_in_graph_metadata_of_an_old_snapshot(
    client, org
):
    """Snapshots saved before the secret FKs landed can hold a Telegram bot key (and other
    credentials) in plaintext inside the graph-level metadata; preview must never return them."""
    graph = _graph_with_python_nodes(org=org, name="old-telegram-flow", node_count=1)
    version = GraphVersioningService().save_version(graph, name="old")

    old_snapshot = version.snapshot
    old_snapshot["metadata"] = {
        "nodes": [
            {
                "id": "telegram-node-uuid",
                "type": "telegram-trigger",
                "position": {"x": 10, "y": 20},
                "data": {"telegram_bot_api_key": "123456:PLAINTEXT-BOT-KEY", "fields": {}},
            },
            {
                "id": "llm-node-uuid",
                "type": "llm",
                "data": {"llm_config": {"api_key": "sk-PLAINTEXT-LLM-KEY", "model": "gpt"}},
            },
        ],
    }
    GraphVersion.objects.filter(pk=version.pk).update(snapshot=old_snapshot)

    response = _preview(client=client, version_id=version.id)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert "PLAINTEXT" not in response.content.decode()
    telegram_node, llm_node = response.data["snapshot"]["metadata"]["nodes"]
    assert telegram_node["data"]["telegram_bot_api_key"] is None
    assert telegram_node["position"] == {"x": 10, "y": 20}
    assert llm_node["data"]["llm_config"] == {"api_key": None, "model": "gpt"}


@pytest.mark.django_db
def test_preview_query_count_does_not_grow_with_node_count(
    client, org, django_assert_num_queries
):
    small_version = GraphVersioningService().save_version(
        _graph_with_python_nodes(org=org, name="one-node", node_count=1), name="small"
    )
    large_version = GraphVersioningService().save_version(
        _graph_with_python_nodes(org=org, name="five-nodes", node_count=5), name="large"
    )

    with CaptureQueriesContext(connection) as small_queries:
        small_response = _preview(client=client, version_id=small_version.id)
    assert small_response.status_code == status.HTTP_200_OK, small_response.content

    with django_assert_num_queries(len(small_queries.captured_queries)):
        large_response = _preview(client=client, version_id=large_version.id)
    assert large_response.status_code == status.HTTP_200_OK, large_response.content
    assert len(large_response.data["snapshot"]["nodes"]) == 5
