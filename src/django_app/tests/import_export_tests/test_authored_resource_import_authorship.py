import pytest
from django.urls import reverse
from rest_framework import status

from rbac.identity.api_keys.principals import SystemServicePrincipal
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.models import Graph
from tables.models.graph_models import GraphNote
from tables.models.mcp_models import McpTool
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


@pytest.fixture
def exported_mcp_tool(beta, member_only) -> dict:
    tool = McpTool.objects.create(
        name="exported-tool",
        transport="http://mcp.example.com/sse",
        tool_name="search",
        org=beta,
        created_by=member_only,
    )
    return ExportService(entity_registry).export_entities(EntityType.MCP_TOOL, [tool.id])


@pytest.fixture
def exported_note(acme) -> dict:
    source = Graph.objects.create(name="note-source", org=acme)
    note = GraphNote.objects.create(graph=source, content="imported note")
    node_ref = NodeRef(entity_type=EntityType.NOTE_NODE, node_id=note.id)
    return GraphPartialExportService(entity_registry).export([node_ref]).data


def _partial_import(client_as, user, org, graph, export_data):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-partial-import", args=[graph.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )


# ---- import stamps new rows through resolve_author ----


@pytest.mark.django_db
def test_import_authors_new_row_with_importing_user(exported_mcp_tool, acme, admin_acme):
    ImportService(entity_registry).import_data(
        exported_mcp_tool, main_entity=EntityType.MCP_TOOL, org_id=acme.id, user=admin_acme
    )

    assert McpTool.objects.get(org=acme, name="exported-tool").created_by_id == admin_acme.id


@pytest.mark.django_db
def test_import_by_system_principal_leaves_new_row_unauthored(exported_mcp_tool, acme):
    ImportService(entity_registry).import_data(
        exported_mcp_tool,
        main_entity=EntityType.MCP_TOOL,
        org_id=acme.id,
        user=SystemServicePrincipal(),
    )

    assert McpTool.objects.get(org=acme, name="exported-tool").created_by_id is None


# ---- partial import edits the target graph ----


@pytest.mark.django_db
def test_partial_import_claims_unauthored_graph(client_as, admin_acme, acme, exported_note):
    target = Graph.objects.create(name="ownerless-target", org=acme)

    response = _partial_import(client_as, admin_acme, acme, target, exported_note)

    assert response.status_code == status.HTTP_200_OK, response.content
    target.refresh_from_db()
    assert target.created_by_id == admin_acme.id
    assert GraphNote.objects.filter(graph=target).exists()


@pytest.mark.django_db
def test_partial_import_keeps_graph_author(
    client_as, admin_acme, member_only, acme, exported_note
):
    target = Graph.objects.create(name="authored-target", org=acme, created_by=member_only)

    response = _partial_import(client_as, admin_acme, acme, target, exported_note)

    assert response.status_code == status.HTTP_200_OK, response.content
    target.refresh_from_db()
    assert target.created_by_id == member_only.id


@pytest.mark.django_db
def test_cross_org_partial_import_returns_404_and_leaves_graph_unclaimed(
    client_as, admin_acme, acme, beta, exported_note
):
    target = Graph.objects.create(name="beta-target", org=beta)

    response = _partial_import(client_as, admin_acme, acme, target, exported_note)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    target.refresh_from_db()
    assert target.created_by_id is None
