from dataclasses import dataclass
from typing import Callable

import pytest
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from rbac.models import Organization
from tables.models import Graph, Label, LLMConfig
from tables.models.embedding_models import EmbeddingConfig
from tables.models.graph_models import GraphNote
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.models.webhook_models import RealtimeChannel, WebhookTrigger
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

_PYTHON_CODE_DATA = {"code": "def main(): return 1", "entrypoint": "main", "libraries": []}


@dataclass(frozen=True)
class AuthoredResource:
    """How to create a row of one authored resource and edit it over its REST endpoint."""

    basename: str
    model: type
    create_row: Callable[[Organization, str, object], object]
    create_body: Callable[[str], dict]
    patch_body: Callable[[object], dict]


def _create_python_code_tool(org, name, author):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    return PythonCodeTool.objects.create(
        name=name, description="tool", python_code=python_code, org=org, created_by=author
    )


RESOURCES = [
    AuthoredResource(
        basename="graphs",
        model=Graph,
        create_row=lambda org, name, author: Graph.objects.create(
            name=name, org=org, created_by=author
        ),
        create_body=lambda name: {"name": name},
        patch_body=lambda row: {"description": "edited", "save_version": row.save_version},
    ),
    AuthoredResource(
        basename="pythoncodetool",
        model=PythonCodeTool,
        create_row=_create_python_code_tool,
        create_body=lambda name: {
            "name": name,
            "description": "tool",
            "python_code": _PYTHON_CODE_DATA,
        },
        patch_body=lambda row: {"description": "edited"},
    ),
    AuthoredResource(
        basename="mcptool",
        model=McpTool,
        create_row=lambda org, name, author: McpTool.objects.create(
            name=name,
            transport="http://mcp.example.com/sse",
            tool_name="search",
            org=org,
            created_by=author,
        ),
        create_body=lambda name: {
            "name": name,
            "transport": "http://mcp.example.com/sse",
            "tool_name": "search",
        },
        patch_body=lambda row: {"timeout": 5},
    ),
    AuthoredResource(
        basename="llmconfig",
        model=LLMConfig,
        create_row=lambda org, name, author: LLMConfig.objects.create(
            custom_name=name, org=org, created_by=author
        ),
        create_body=lambda name: {"custom_name": name},
        patch_body=lambda row: {"temperature": 0.7},
    ),
    AuthoredResource(
        basename="embeddingconfig",
        model=EmbeddingConfig,
        create_row=lambda org, name, author: EmbeddingConfig.objects.create(
            custom_name=name, org=org, created_by=author
        ),
        create_body=lambda name: {"custom_name": name},
        patch_body=lambda row: {"is_visible": False},
    ),
    AuthoredResource(
        basename="realtimechannel",
        model=RealtimeChannel,
        create_row=lambda org, name, author: RealtimeChannel.objects.create(
            name=name, org=org, created_by=author
        ),
        create_body=lambda name: {"name": name},
        patch_body=lambda row: {"name": f"{row.name}-edited"},
    ),
    AuthoredResource(
        basename="webhooktrigger",
        model=WebhookTrigger,
        create_row=lambda org, name, author: WebhookTrigger.objects.create(
            path=name, org=org, created_by=author
        ),
        create_body=lambda name: {"path": name},
        patch_body=lambda row: {"path": f"{row.path}-edited"},
    ),
]
RESOURCE_IDS = [resource.basename for resource in RESOURCES]


@pytest.fixture
def acme_client(client_as, admin_acme, acme) -> APIClient:
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def system_key_client(issue_api_key, acme) -> APIClient:
    raw_key, _ = issue_api_key(user=None, name="authorship-system-key")
    client = APIClient()
    client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _list_url(basename: str) -> str:
    return reverse(f"{basename}-list")


def _detail_url(basename: str, pk: int) -> str:
    return reverse(f"{basename}-detail", args=[pk])


def _author_id(model, pk: int) -> int | None:
    return model._base_manager.values_list("created_by_id", flat=True).get(pk=pk)


# ---- create ----


@pytest.mark.django_db
@pytest.mark.parametrize("resource", RESOURCES, ids=RESOURCE_IDS)
def test_create_stamps_acting_user_and_ignores_body_author(
    resource, acme_client, admin_acme, member_only
):
    body = {**resource.create_body("created-row"), "created_by": member_only.id}

    response = acme_client.post(_list_url(resource.basename), body, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _author_id(resource.model, response.data["id"]) == admin_acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("resource", RESOURCES, ids=RESOURCE_IDS)
def test_create_with_system_api_key_leaves_author_empty(resource, system_key_client, acme):
    response = system_key_client.post(
        _list_url(resource.basename), resource.create_body("system-row"), format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    row = resource.model._base_manager.get(pk=response.data["id"])
    assert row.org_id == acme.id
    assert row.created_by_id is None


@pytest.mark.django_db
def test_create_with_system_api_key_leaves_author_empty_without_stamping_serializer(
    system_key_client, acme
):
    response = system_key_client.post(_list_url("label"), {"name": "system-label"}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    label = Label.objects.get(pk=response.data["id"])
    assert label.org_id == acme.id
    assert label.created_by_id is None


# ---- edit: claim an ownerless row, never replace an author ----


@pytest.mark.django_db
@pytest.mark.parametrize("resource", RESOURCES, ids=RESOURCE_IDS)
def test_patch_of_unauthored_row_claims_it_for_editor(resource, acme_client, admin_acme, acme):
    row = resource.create_row(acme, "ownerless-row", None)

    response = acme_client.patch(
        _detail_url(resource.basename, row.pk), resource.patch_body(row), format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(resource.model, row.pk) == admin_acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("resource", RESOURCES, ids=RESOURCE_IDS)
def test_patch_of_unauthored_row_ignores_body_author(
    resource, acme_client, admin_acme, member_only, acme
):
    row = resource.create_row(acme, "ownerless-row", None)
    body = {**resource.patch_body(row), "created_by": member_only.id}

    response = acme_client.patch(_detail_url(resource.basename, row.pk), body, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(resource.model, row.pk) == admin_acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("resource", RESOURCES, ids=RESOURCE_IDS)
def test_patch_of_authored_row_keeps_author(resource, acme_client, admin_acme, member_only, acme):
    row = resource.create_row(acme, "authored-row", member_only)
    body = {**resource.patch_body(row), "created_by": admin_acme.id}

    response = acme_client.patch(_detail_url(resource.basename, row.pk), body, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(resource.model, row.pk) == member_only.id


@pytest.mark.django_db
@pytest.mark.parametrize("resource", RESOURCES, ids=RESOURCE_IDS)
def test_cross_org_patch_returns_404_and_leaves_row_unclaimed(resource, acme_client, beta):
    row = resource.create_row(beta, "beta-row", None)

    response = acme_client.patch(
        _detail_url(resource.basename, row.pk), resource.patch_body(row), format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert _author_id(resource.model, row.pk) is None


# ---- resource-specific edit paths ----


@pytest.mark.django_db
def test_flow_save_claims_unauthored_graph(acme_client, admin_acme, acme):
    graph = Graph.objects.create(name="ownerless-flow", org=acme)
    payload = {
        "save_version": graph.save_version,
        "graph_note_list": [{"graph": graph.id, "content": "note", "metadata": {}}],
    }

    response = acme_client.post(reverse("graphs-save-flow", args=[graph.id]), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(Graph, graph.pk) == admin_acme.id


@pytest.mark.django_db
def test_flow_save_keeps_graph_author(acme_client, member_only, acme):
    graph = Graph.objects.create(name="authored-flow", org=acme, created_by=member_only)
    payload = {
        "save_version": graph.save_version,
        "graph_note_list": [{"graph": graph.id, "content": "note", "metadata": {}}],
    }

    response = acme_client.post(reverse("graphs-save-flow", args=[graph.id]), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(Graph, graph.pk) == member_only.id
    assert GraphNote.objects.filter(graph=graph).exists()


@pytest.mark.django_db
def test_flow_save_without_changes_leaves_graph_unclaimed(acme_client, acme):
    graph = Graph.objects.create(name="ownerless-untouched-flow", org=acme)
    note = GraphNote.objects.create(graph=graph, content="note", metadata={})
    graph.refresh_from_db()
    payload = {
        "save_version": graph.save_version,
        "graph_note_list": [
            {"id": note.id, "graph": graph.id, "content": "note", "metadata": {}}
        ],
    }

    response = acme_client.post(reverse("graphs-save-flow", args=[graph.id]), payload, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(Graph, graph.pk) is None


NODE_WRITES = ["create", "update", "delete"]


def _write_note(client, graph, write: str):
    if write == "create":
        return client.post(
            reverse("graphnote-list"),
            {"graph": graph.id, "content": "new", "metadata": {}},
            format="json",
        )
    note = GraphNote.objects.create(graph=graph, content="note")
    if write == "update":
        return client.patch(
            reverse("graphnote-detail", args=[note.pk]), {"content": "edited"}, format="json"
        )
    return client.delete(reverse("graphnote-detail", args=[note.pk]))


@pytest.mark.django_db
@pytest.mark.parametrize("write", NODE_WRITES)
def test_node_write_claims_unauthored_graph(write, acme_client, admin_acme, acme):
    graph = Graph.objects.create(name="ownerless-node-flow", org=acme)

    response = _write_note(acme_client, graph, write)

    assert response.status_code < 300, response.content
    assert _author_id(Graph, graph.pk) == admin_acme.id


@pytest.mark.django_db
@pytest.mark.parametrize("write", NODE_WRITES)
def test_node_write_keeps_graph_author(write, acme_client, member_only, acme):
    graph = Graph.objects.create(name="authored-node-flow", org=acme, created_by=member_only)

    response = _write_note(acme_client, graph, write)

    assert response.status_code < 300, response.content
    assert _author_id(Graph, graph.pk) == member_only.id


@pytest.mark.django_db
@pytest.mark.parametrize("write", NODE_WRITES)
def test_node_write_with_system_api_key_leaves_graph_unauthored(write, system_key_client, acme):
    graph = Graph.objects.create(name="system-node-flow", org=acme)

    response = _write_note(system_key_client, graph, write)

    assert response.status_code < 300, response.content
    assert _author_id(Graph, graph.pk) is None


@pytest.mark.django_db
def test_cross_org_node_write_returns_404_and_leaves_graph_unclaimed(acme_client, beta):
    graph = Graph.objects.create(name="beta-node-flow", org=beta)

    response = _write_note(acme_client, graph, "update")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert _author_id(Graph, graph.pk) is None


@pytest.mark.django_db
def test_cross_org_flow_save_returns_404_and_leaves_graph_unclaimed(acme_client, beta):
    graph = Graph.objects.create(name="beta-flow", org=beta)

    response = acme_client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version},
        format="json",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert _author_id(Graph, graph.pk) is None


@pytest.mark.django_db
def test_label_patch_on_built_in_tool_succeeds_and_leaves_it_unauthored(acme_client, acme):
    python_code = PythonCode.objects.create(code="def main(): return 1", entrypoint="main")
    built_in_tool = PythonCodeTool.objects.create(
        name="built-in-tool", description="tool", python_code=python_code, built_in=True
    )
    label = Label.objects.create(name="tool-label", org=acme, scope=Label.Scope.TOOL)

    response = acme_client.patch(
        _detail_url("pythoncodetool", built_in_tool.pk), {"labels": [label.id]}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _author_id(PythonCodeTool, built_in_tool.pk) is None
    assert list(built_in_tool.labels.values_list("id", flat=True)) == [label.id]
