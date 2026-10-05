"""Import and copy record the acting user as the last editor of every row they create."""

import json
from datetime import UTC, datetime

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied

from rbac.authorship import record_last_edit
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import ResourceLastEdit
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.schemas import ImportSettings
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.import_service import ImportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.strategies.nodes.node_maps import (
    NODE_RELATIONS,
    NODE_TYPE_TO_ENTITY_TYPE,
)
from tables.models import Graph
from tables.models.graph_models import GraphNote
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tables.services.copy_services.mcp_tool_copy_service import McpToolCopyService
from tables.services.copy_services.python_code_tool_copy_service import (
    PythonCodeToolCopyService,
)
from tests.helpers import data_to_json_file
from tests.import_export_tests.test_node_authorship_import_export import (
    _create_every_node_type,
)
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.user_summary_helpers import expected_user_summary

PREVIOUS_EDIT_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC)
STRUCTURAL_NODE_TYPES = {NodeType.START_NODE, NodeType.END_NODE}
LAST_EDIT_UPSERT_PREFIX = 'INSERT INTO "rbac_resourcelastedit"'


@pytest.fixture(autouse=True)
def _telegram_registration_mocked(mock_telegram_service):
    return mock_telegram_service


def _last_edit_of(instance) -> ResourceLastEdit | None:
    return ResourceLastEdit.objects.filter(
        content_type=ContentType.objects.get_for_model(instance), object_id=instance.pk
    ).first()


def _graph_nodes(graph: Graph) -> list:
    return [
        node
        for relation_name in NODE_RELATIONS.values()
        for node in getattr(graph, relation_name).all()
    ]


def _assert_last_edited_by(resources, user, *, since) -> None:
    for resource in resources:
        last_edit = _last_edit_of(resource)
        assert last_edit is not None, resource
        assert last_edit.edited_by_id == user.id, resource
        assert last_edit.edited_at >= since, resource


def _export(graph: Graph) -> dict:
    return ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])


def _client_in(client_as, user, org):
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client


def _import_flow(client, export_data):
    return client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json")},
        format="multipart",
    )


def _imported_graph(response, source_flow: Graph) -> Graph:
    assert response.status_code == status.HTTP_200_OK, response.content
    return Graph.objects.exclude(pk=source_flow.pk).get(org_id=source_flow.org_id)


def _python_code() -> PythonCode:
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


def _mcp_tool(org, name: str) -> McpTool:
    return McpTool.objects.create(
        name=name, transport="https://mcp.example.com/sse", tool_name="search", org=org
    )


def _upserts(context) -> int:
    return sum(
        query["sql"].startswith(LAST_EDIT_UPSERT_PREFIX) for query in context.captured_queries
    )


@pytest.fixture
def source_flow(acme, member_only):
    """A flow of acme holding every node type, each last edited by `member_only` long ago."""
    graph = Graph.objects.create(name="edited-flow", org=acme, metadata={"nodes": [], "edges": []})
    record_last_edit(graph, member_only, edited_at=PREVIOUS_EDIT_AT)
    for node in _create_every_node_type(graph, member_only):
        record_last_edit(node, member_only, edited_at=PREVIOUS_EDIT_AT)
    return graph


# ---- full import ----


@pytest.mark.django_db
def test_full_import_records_importer_on_graph_and_every_node(
    client_as, admin_acme, acme, source_flow
):
    import_started_at = timezone.now()

    response = _import_flow(_client_in(client_as, admin_acme, acme), _export(source_flow))

    imported_graph = _imported_graph(response, source_flow)
    imported_nodes = _graph_nodes(imported_graph)
    assert len(imported_nodes) == len(NODE_RELATIONS)
    _assert_last_edited_by([imported_graph, *imported_nodes], admin_acme, since=import_started_at)
    assert _last_edit_of(source_flow).edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_import_file_cannot_set_last_edit(client_as, admin_acme, member_only, acme, source_flow):
    export_data = _export(source_flow)
    graph_data = export_data[EntityType.GRAPH][0]
    graph_data["last_edited_by"] = member_only.id
    graph_data["last_edited_at"] = PREVIOUS_EDIT_AT.isoformat()
    graph_data["node_last_edit"] = {
        str(node_data["id"]): {"edited_by": member_only.id, "edited_at": PREVIOUS_EDIT_AT.isoformat()}
        for node_data in graph_data["nodes"]
    }
    for node_data in graph_data["nodes"]:
        node_data["last_edited_by"] = member_only.id
        node_data["last_edited_at"] = PREVIOUS_EDIT_AT.isoformat()
    import_started_at = timezone.now()

    response = _import_flow(_client_in(client_as, admin_acme, acme), export_data)

    imported_graph = _imported_graph(response, source_flow)
    _assert_last_edited_by(
        [imported_graph, *_graph_nodes(imported_graph)], admin_acme, since=import_started_at
    )


@pytest.mark.django_db
def test_graph_export_carries_no_last_edit_data(source_flow):
    exported = json.dumps(_export(source_flow), default=str)

    assert "last_edited" not in exported
    assert "node_last_edit" not in exported
    assert "edited_by" not in exported


@pytest.mark.django_db
def test_import_records_importer_on_created_dependencies_only(
    acme, beta, admin_acme, member_only
):
    source = Graph.objects.create(name="dependency-flow", org=acme)
    reused_tool = _mcp_tool(acme, "already-here")
    record_last_edit(reused_tool, member_only, edited_at=PREVIOUS_EDIT_AT)
    foreign_tool = _mcp_tool(beta, "brought-in")
    tool_bundle = ExportService(entity_registry).export_entities(
        EntityType.MCP_TOOL, [reused_tool.id]
    )[EntityType.MCP_TOOL] + ExportService(entity_registry).export_entities(
        EntityType.MCP_TOOL, [foreign_tool.id]
    )[EntityType.MCP_TOOL]
    bundle = {**_export(source), EntityType.MCP_TOOL: tool_bundle}
    import_started_at = timezone.now()

    ImportService(entity_registry).import_data(
        bundle, main_entity=EntityType.GRAPH, org_id=acme.id, user=admin_acme
    )

    created_tool = McpTool.objects.get(org=acme, name="brought-in")
    imported_graph = Graph.objects.exclude(pk=source.pk).get(org=acme)
    _assert_last_edited_by([created_tool, imported_graph], admin_acme, since=import_started_at)
    reused_last_edit = _last_edit_of(reused_tool)
    assert reused_last_edit.edited_by_id == member_only.id
    assert reused_last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_import_of_main_entity_records_importer(beta, acme, admin_acme):
    exported_tool = ExportService(entity_registry).export_entities(
        EntityType.MCP_TOOL, [_mcp_tool(beta, "exported-tool").id]
    )

    ImportService(entity_registry).import_data(
        exported_tool, main_entity=EntityType.MCP_TOOL, org_id=acme.id, user=admin_acme
    )

    assert _last_edit_of(McpTool.objects.get(org=acme)).edited_by_id == admin_acme.id


@pytest.mark.django_db
def test_import_denied_by_permissions_records_nothing(beta, acme, member_only):
    exported_tool = ExportService(entity_registry).export_entities(
        EntityType.MCP_TOOL, [_mcp_tool(beta, "exported-tool").id]
    )
    denied_permissions = type("Denied", (), {"can": lambda self, resource, permission: False})()

    with pytest.raises(PermissionDenied):
        ImportService(entity_registry).import_data(
            exported_tool,
            main_entity=EntityType.MCP_TOOL,
            org_id=acme.id,
            user=member_only,
            effective_permissions=denied_permissions,
        )

    assert not ResourceLastEdit.objects.filter(edited_by=member_only).exists()


@pytest.mark.django_db
def test_import_without_acting_user_records_nothing(acme, source_flow):
    graph_strategy = entity_registry.get_strategy(EntityType.GRAPH)
    graph_data = _export(source_flow)[EntityType.GRAPH][0]

    imported_graph = graph_strategy.create_entity(graph_data, IDMapper(), org_id=acme.id, user=None)

    assert all(_last_edit_of(node) is None for node in _graph_nodes(imported_graph))


@pytest.mark.django_db
def test_import_by_system_principal_records_time_without_editor(acme, source_flow):
    import_started_at = timezone.now()

    ImportService(entity_registry).import_data(
        _export(source_flow),
        main_entity=EntityType.GRAPH,
        org_id=acme.id,
        user=SystemServicePrincipal(),
    )

    imported_graph = Graph.objects.exclude(pk=source_flow.pk).get(org=acme)
    for resource in (imported_graph, *_graph_nodes(imported_graph)):
        last_edit = _last_edit_of(resource)
        assert last_edit.edited_by_id is None
        assert last_edit.edited_at >= import_started_at


def _count_import_upserts(acme, user, node_count: int) -> int:
    source = Graph.objects.create(name=f"flow-{node_count}", org=acme)
    for index in range(node_count):
        GraphNote.objects.create(graph=source, content=f"note {index}")
    with CaptureQueriesContext(connection) as context:
        ImportService(entity_registry).import_data(
            _export(source), main_entity=EntityType.GRAPH, org_id=acme.id, user=user
        )
    return _upserts(context)


@pytest.mark.django_db
def test_import_records_last_edits_in_a_fixed_number_of_statements(acme, admin_acme):
    assert _count_import_upserts(acme, admin_acme, 1) == _count_import_upserts(
        acme, admin_acme, 5
    )


# ---- partial import ----


@pytest.mark.django_db
def test_partial_import_records_importer_on_new_nodes_and_target_graph(
    client_as, admin_acme, member_only, acme, source_flow
):
    node_refs = [
        NodeRef(entity_type=NODE_TYPE_TO_ENTITY_TYPE[node_type], node_id=node.id)
        for node_type, relation_name in NODE_RELATIONS.items()
        if node_type not in STRUCTURAL_NODE_TYPES
        for node in getattr(source_flow, relation_name).all()
    ]
    export_data = GraphPartialExportService(entity_registry).export(node_refs).data
    existing_nodes = set(_graph_nodes(source_flow))
    import_started_at = timezone.now()

    response = _client_in(client_as, admin_acme, acme).post(
        reverse("graphs-partial-import", args=[source_flow.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    new_nodes = [node for node in _graph_nodes(source_flow) if node not in existing_nodes]
    assert len(new_nodes) == len(node_refs)
    _assert_last_edited_by([source_flow, *new_nodes], admin_acme, since=import_started_at)
    for node in existing_nodes:
        assert _last_edit_of(node).edited_by_id == member_only.id


@pytest.mark.django_db
def test_cross_org_partial_import_returns_404_and_records_nothing(
    client_as, admin_acme, acme, beta
):
    source = Graph.objects.create(name="note-source", org=acme)
    note = GraphNote.objects.create(graph=source, content="imported note")
    export_data = (
        GraphPartialExportService(entity_registry)
        .export([NodeRef(entity_type=EntityType.NOTE_NODE, node_id=note.id)])
        .data
    )
    target = Graph.objects.create(name="beta-target", org=beta)

    response = _client_in(client_as, admin_acme, acme).post(
        reverse("graphs-partial-import", args=[target.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not ResourceLastEdit.objects.filter(edited_by=admin_acme).exists()


# ---- copy ----


@pytest.mark.django_db
def test_graph_copy_records_copier_on_graph_and_every_node(
    client_as, admin_acme, member_only, acme, source_flow
):
    copy_started_at = timezone.now()

    response = _client_in(client_as, admin_acme, acme).post(
        reverse("graphs-copy", args=[source_flow.id]), {}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    copied_graph = Graph.objects.get(pk=response.data["id"])
    copied_nodes = _graph_nodes(copied_graph)
    assert len(copied_nodes) == len(NODE_RELATIONS)
    _assert_last_edited_by([copied_graph, *copied_nodes], admin_acme, since=copy_started_at)
    assert _last_edit_of(source_flow).edited_by_id == member_only.id
    assert all(
        _last_edit_of(node).edited_by_id == member_only.id for node in _graph_nodes(source_flow)
    )


@pytest.mark.django_db
def test_graph_copy_records_all_last_edits_in_one_statement(admin_acme, source_flow):
    with CaptureQueriesContext(connection) as context:
        GraphCopyService().copy(source_flow, user=admin_acme)

    assert _upserts(context) == 1


@pytest.mark.django_db
def test_graph_copy_without_acting_user_records_nothing(source_flow):
    copied_graph = GraphCopyService().copy(source_flow, user=None)

    assert _last_edit_of(copied_graph) is None
    assert all(_last_edit_of(node) is None for node in _graph_nodes(copied_graph))


@pytest.mark.django_db
def test_cross_org_graph_copy_returns_404_and_records_nothing(
    client_as, admin_acme, acme, beta
):
    foreign_flow = Graph.objects.create(name="beta-flow", org=beta)

    response = _client_in(client_as, admin_acme, acme).post(
        reverse("graphs-copy", args=[foreign_flow.id]), {}, format="json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert not ResourceLastEdit.objects.filter(edited_by=admin_acme).exists()


@pytest.mark.django_db
def test_python_code_tool_copy_records_copier(client_as, admin_acme, member_only, acme):
    tool = PythonCodeTool.objects.create(
        name="edited tool", description="description", python_code=_python_code(), org=acme
    )
    record_last_edit(tool, member_only, edited_at=PREVIOUS_EDIT_AT)

    response = _client_in(client_as, admin_acme, acme).post(
        f"/api/python-code-tool/{tool.id}/copy/", {}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _last_edit_of(PythonCodeTool.objects.get(pk=response.data["id"])).edited_by_id == (
        admin_acme.id
    )
    assert response.data["last_edited_by"] == expected_user_summary(admin_acme)
    assert _last_edit_of(tool).edited_by_id == member_only.id


@pytest.mark.django_db
def test_mcp_tool_copy_records_copier(client_as, admin_acme, member_only, acme):
    tool = _mcp_tool(acme, "edited mcp")
    record_last_edit(tool, member_only, edited_at=PREVIOUS_EDIT_AT)

    response = _client_in(client_as, admin_acme, acme).post(
        f"/api/mcp-tools/{tool.id}/copy/", {}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert _last_edit_of(McpTool.objects.get(pk=response.data["id"])).edited_by_id == (
        admin_acme.id
    )
    assert response.data["last_edited_by"] == expected_user_summary(admin_acme)
    assert _last_edit_of(tool).edited_by_id == member_only.id


@pytest.mark.django_db
def test_tool_copies_without_acting_user_record_nothing(acme):
    python_tool = PythonCodeTool.objects.create(
        name="tool", description="description", python_code=_python_code(), org=acme
    )

    python_copy = PythonCodeToolCopyService().copy(python_tool, user=None)
    mcp_copy = McpToolCopyService().copy(_mcp_tool(acme, "mcp"), user=None)

    assert _last_edit_of(python_copy) is None
    assert _last_edit_of(mcp_copy) is None


@pytest.mark.django_db
def test_import_replacing_a_flow_in_place_records_importer_on_graph_and_new_nodes(
    acme, admin_acme, member_only, source_flow
):
    export_data = _export(source_flow)
    import_started_at = timezone.now()

    ImportService(entity_registry).import_data(
        export_data,
        main_entity=EntityType.GRAPH,
        settings=ImportSettings(preserve_uuids=True, replace_existing=True),
        org_id=acme.id,
        user=admin_acme,
    )

    assert Graph.objects.filter(org=acme).count() == 1
    replaced_nodes = _graph_nodes(source_flow)
    assert len(replaced_nodes) == len(NODE_RELATIONS)
    _assert_last_edited_by([source_flow, *replaced_nodes], admin_acme, since=import_started_at)


@pytest.mark.django_db
def test_partial_import_that_adds_nothing_records_nothing(
    client_as, admin_acme, member_only, acme
):
    target = Graph.objects.create(name="untouched-target", org=acme)
    record_last_edit(target, member_only, edited_at=PREVIOUS_EDIT_AT)
    export_data = {EntityType.CREW_NODE: [{"id": 5, "node_name": "retired crew node"}]}

    response = _client_in(client_as, admin_acme, acme).post(
        reverse("graphs-partial-import", args=[target.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _graph_nodes(target) == []
    last_edit = _last_edit_of(target)
    assert last_edit.edited_by_id == member_only.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT


@pytest.mark.django_db
def test_partial_import_creating_only_dependencies_records_them_but_not_the_graph(
    client_as, admin_acme, member_only, acme, beta
):
    target = Graph.objects.create(name="dependency-only-target", org=acme)
    record_last_edit(target, member_only, edited_at=PREVIOUS_EDIT_AT)
    exported_tool = ExportService(entity_registry).export_entities(
        EntityType.MCP_TOOL, [_mcp_tool(beta, "dependency-only-tool").id]
    )[EntityType.MCP_TOOL]
    export_data = {
        EntityType.MCP_TOOL: exported_tool,
        EntityType.CREW_NODE: [{"id": 5, "node_name": "retired crew node"}],
    }
    import_started_at = timezone.now()

    response = _client_in(client_as, admin_acme, acme).post(
        reverse("graphs-partial-import", args=[target.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert _graph_nodes(target) == []
    created_tool = McpTool.objects.get(org=acme, name="dependency-only-tool")
    _assert_last_edited_by([created_tool], admin_acme, since=import_started_at)
    last_edit = _last_edit_of(target)
    assert last_edit.edited_by_id == member_only.id
    assert last_edit.edited_at == PREVIOUS_EDIT_AT
