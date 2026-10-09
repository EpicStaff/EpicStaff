import pytest
from django.apps import apps
from django.urls import reverse
from rest_framework import status

from rbac.governance.memberships import MembershipManagementService
from rbac.identity.api_keys.principals import SystemServicePrincipal
from rbac.models import OrganizationUser
from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType, NodeType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.strategies.nodes.node_maps import (
    NODE_RELATIONS,
    NODE_TYPE_TO_ENTITY_TYPE,
)
from tables.models import Graph
from tables.models.base_models import GraphAuthorModel
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    DecisionTableNode,
    EndNode,
    FileExtractorNode,
    GraphNote,
    KeyValueNode,
    KnowledgeNode,
    PythonNode,
    ScheduleTriggerNode,
    StartNode,
    SubGraphNode,
    TaskNode,
    TelegramTriggerNode,
    WebhookTriggerNode,
)
from tables.models.mcp_models import McpTool
from tables.models.python_models import PythonCode, PythonCodeTool
from tables.services.copy_services.graph_copy_service import GraphCopyService
from tests.helpers import data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

AUTHOR_KEY = "created_by"
STRUCTURAL_NODE_TYPES = {NodeType.START_NODE, NodeType.END_NODE}


@pytest.fixture(autouse=True)
def _telegram_registration_mocked(mock_telegram_service):
    return mock_telegram_service


def _python_code() -> PythonCode:
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


def _create_every_node_type(graph: Graph, author) -> list:
    """Create one node of every authored node type in `graph`, authored by `author`."""
    return [
        StartNode.objects.create(graph=graph, variables={}, created_by=author),
        EndNode.objects.create(graph=graph, output_map={}, created_by=author),
        GraphNote.objects.create(graph=graph, content="note", created_by=author),
        KeyValueNode.objects.create(graph=graph, node_name="key value", created_by=author),
        WebhookTriggerNode.objects.create(
            graph=graph, node_name="webhook", python_code=_python_code(), created_by=author
        ),
        ScheduleTriggerNode.objects.create(graph=graph, node_name="schedule", created_by=author),
        TelegramTriggerNode.objects.create(graph=graph, node_name="telegram", created_by=author),
        AgentNode.objects.create(graph=graph, node_name="agent", created_by=author),
        TaskNode.objects.create(graph=graph, node_name="task", created_by=author),
        PythonNode.objects.create(
            graph=graph, node_name="python", python_code=_python_code(), created_by=author
        ),
        KnowledgeNode.objects.create(graph=graph, node_name="knowledge", created_by=author),
        FileExtractorNode.objects.create(graph=graph, node_name="extractor", created_by=author),
        AudioTranscriptionNode.objects.create(
            graph=graph, node_name="transcription", created_by=author
        ),
        SubGraphNode.objects.create(graph=graph, node_name="subgraph", created_by=author),
        DecisionTableNode.objects.create(graph=graph, node_name="decision", created_by=author),
        ClassificationDecisionTableNode.objects.create(
            graph=graph, node_name="classification", created_by=author
        ),
    ]


def _graph_nodes(graph: Graph) -> list:
    return [
        node
        for relation_name in NODE_RELATIONS.values()
        for node in getattr(graph, relation_name).all()
    ]


def _node_authors(graph: Graph) -> dict[str, int | None]:
    return {f"{type(node).__name__}#{node.pk}": node.created_by_id for node in _graph_nodes(graph)}


def _keys_named(value, key: str) -> list[str]:
    """Return the path of every dict key equal to `key`, at any depth of `value`."""
    found = []

    def walk(item, path):
        if isinstance(item, dict):
            for item_key, child in item.items():
                child_path = f"{path}.{item_key}"
                if item_key == key:
                    found.append(child_path)
                walk(child, child_path)
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}[{index}]")

    walk(value, "$")
    return found


def _export(graph: Graph) -> dict:
    return ExportService(entity_registry).export_entities(EntityType.GRAPH, [graph.id])


def _import_flow(client, org, export_data):
    client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
    return client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=export_data, filename="flow.json")},
        format="multipart",
    )


def _imported_graph(response, source_flow: Graph) -> Graph:
    assert response.status_code == status.HTTP_200_OK, response.content
    return Graph.objects.exclude(pk=source_flow.pk).get(org_id=source_flow.org_id)


@pytest.fixture
def source_flow(acme, member_only):
    """A flow of acme holding every node type, all authored by `member_only`."""
    graph = Graph.objects.create(
        name="authored-flow",
        org=acme,
        metadata={"nodes": [], "edges": []},
        created_by=member_only,
    )
    _create_every_node_type(graph, member_only)
    return graph


# ---- the fixture really covers every authored node type ----


@pytest.mark.django_db
def test_source_flow_holds_every_graph_authored_node_type(source_flow):
    graph_authored_models = {
        model for model in apps.get_models() if issubclass(model, GraphAuthorModel)
    }

    assert {type(node) for node in _graph_nodes(source_flow)} == graph_authored_models


# ---- export carries no author; a version snapshot only in node_authorship ----


@pytest.mark.django_db
def test_flow_export_carries_no_author_anywhere(source_flow):
    export_data = _export(source_flow)

    assert len(export_data[EntityType.GRAPH][0]["nodes"]) == len(NODE_RELATIONS)
    assert _keys_named(export_data, AUTHOR_KEY) == []


@pytest.mark.django_db
def test_partial_export_carries_no_author_anywhere(source_flow):
    node_refs = [
        NodeRef(entity_type=NODE_TYPE_TO_ENTITY_TYPE[node_type], node_id=node.id)
        for node_type, relation_name in NODE_RELATIONS.items()
        if node_type not in STRUCTURAL_NODE_TYPES
        for node in getattr(source_flow, relation_name).all()
    ]

    result = GraphPartialExportService(entity_registry).export(
        node_refs, org_id=source_flow.org_id
    )

    assert not result.has_errors, result.errors
    assert _keys_named(result.data, AUTHOR_KEY) == []


@pytest.mark.django_db
def test_version_snapshot_records_authors_only_in_node_authorship(source_flow):
    version = GraphVersioningService().save_version(graph=source_flow, name="v1")
    export_format_part = {
        key: value for key, value in version.snapshot.items() if key != "node_authorship"
    }

    assert len(version.snapshot["nodes"]) == len(NODE_RELATIONS)
    assert _keys_named(export_format_part, AUTHOR_KEY) == []


# ---- import authors every new row with the importing user ----


@pytest.mark.django_db
def test_full_import_authors_graph_and_every_node_with_importer(
    client_as, admin_acme, acme, source_flow
):
    response = _import_flow(client_as(admin_acme), acme, _export(source_flow))

    imported_graph = _imported_graph(response, source_flow)
    assert imported_graph.created_by_id == admin_acme.id
    node_authors = _node_authors(imported_graph)
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {admin_acme.id}


@pytest.mark.django_db
def test_import_file_cannot_choose_node_author(client_as, admin_acme, member_only, acme, source_flow):
    export_data = _export(source_flow)
    for node_data in export_data[EntityType.GRAPH][0]["nodes"]:
        node_data[AUTHOR_KEY] = member_only.id

    response = _import_flow(client_as(admin_acme), acme, export_data)

    assert set(_node_authors(_imported_graph(response, source_flow)).values()) == {admin_acme.id}


@pytest.mark.django_db
def test_import_file_with_author_of_unknown_user_still_imports(
    client_as, admin_acme, acme, source_flow
):
    export_data = _export(source_flow)
    for node_data in export_data[EntityType.GRAPH][0]["nodes"]:
        node_data[AUTHOR_KEY] = 987654321

    response = _import_flow(client_as(admin_acme), acme, export_data)

    assert set(_node_authors(_imported_graph(response, source_flow)).values()) == {admin_acme.id}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "acting_user", [None, SystemServicePrincipal()], ids=["no-user", "system-principal"]
)
def test_import_without_a_real_user_leaves_nodes_unauthored(acme, source_flow, acting_user):
    graph_strategy = entity_registry.get_strategy(EntityType.GRAPH)
    graph_data = _export(source_flow)[EntityType.GRAPH][0]

    imported_graph = graph_strategy.create_entity(
        graph_data, IDMapper(), org_id=acme.id, user=acting_user
    )

    node_authors = _node_authors(imported_graph)
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {None}


@pytest.mark.django_db
def test_partial_import_authors_every_new_node_with_importer(
    client_as, admin_acme, acme, source_flow
):
    node_refs = [
        NodeRef(entity_type=NODE_TYPE_TO_ENTITY_TYPE[node_type], node_id=node.id)
        for node_type, relation_name in NODE_RELATIONS.items()
        if node_type not in STRUCTURAL_NODE_TYPES
        for node in getattr(source_flow, relation_name).all()
    ]
    export_data = (
        GraphPartialExportService(entity_registry)
        .export(node_refs, org_id=source_flow.org_id)
        .data
    )
    existing_node_keys = set(_node_authors(source_flow))
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("graphs-partial-import", args=[source_flow.id]),
        {"file": data_to_json_file(data=export_data, filename="nodes.json")},
        format="multipart",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    new_node_authors = {
        key: author_id
        for key, author_id in _node_authors(source_flow).items()
        if key not in existing_node_keys
    }
    assert len(new_node_authors) == len(node_refs)
    assert set(new_node_authors.values()) == {admin_acme.id}


# ---- restore replays recorded node authors; create-from-version uses the actor ----


@pytest.mark.django_db
def test_version_restore_keeps_recorded_node_author_who_is_still_a_member(
    client_as, admin_acme, member_only, acme, source_flow
):
    version = GraphVersioningService().save_version(graph=source_flow, name="v1")
    source_flow.refresh_from_db()
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("graph-versions-restore", args=[version.id]),
        {"save_version": source_flow.save_version},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node_authors = _node_authors(source_flow)
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {member_only.id}


@pytest.mark.django_db
def test_version_restore_leaves_nodes_of_a_former_member_unauthored(
    client_as, admin_acme, member_only, acme, source_flow
):
    version = GraphVersioningService().save_version(graph=source_flow, name="v1")
    MembershipManagementService().remove_member(
        actor=admin_acme,
        membership_id=OrganizationUser.objects.get(user=member_only, org=acme).id,
    )
    source_flow.refresh_from_db()
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("graph-versions-restore", args=[version.id]),
        {"save_version": source_flow.save_version},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node_authors = _node_authors(source_flow)
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {None}


@pytest.mark.django_db
def test_graph_from_version_is_authored_with_acting_user(
    client_as, admin_acme, member_only, acme, source_flow
):
    version = GraphVersioningService().save_version(graph=source_flow, name="v1")
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(reverse("graph-versions-create-graph", args=[version.id]))

    assert response.status_code == status.HTTP_201_CREATED, response.content
    new_graph = Graph.objects.get(pk=response.data["graph_id"])
    assert new_graph.created_by_id == admin_acme.id
    node_authors = _node_authors(new_graph)
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {admin_acme.id}
    assert source_flow.created_by_id == member_only.id


def _restore(client, version, graph: Graph):
    graph.refresh_from_db()
    return client.post(
        reverse("graph-versions-restore", args=[version.id]),
        {"save_version": graph.save_version},
        format="json",
    )


@pytest.mark.django_db
def test_version_restore_leaves_unauthored_graph_unauthored(
    client_as, admin_acme, acme, source_flow
):
    Graph.objects.filter(pk=source_flow.pk).update(created_by=None)
    version = GraphVersioningService().save_version(graph=source_flow, name="v1")
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = _restore(client, version, source_flow)

    assert response.status_code == status.HTTP_200_OK, response.content
    source_flow.refresh_from_db()
    assert source_flow.created_by_id is None


@pytest.mark.django_db
def test_version_restore_keeps_existing_graph_author(
    client_as, admin_acme, member_only, acme, source_flow
):
    version = GraphVersioningService().save_version(graph=source_flow, name="v1")
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = _restore(client, version, source_flow)

    assert response.status_code == status.HTTP_200_OK, response.content
    source_flow.refresh_from_db()
    assert source_flow.created_by_id == member_only.id


UNKNOWN_USER_ID = 987654321


@pytest.fixture(params=["other-user", "unknown-user"])
def version_with_node_authors(request, source_flow, member_only):
    """A version of `source_flow` whose stored snapshot nodes name an author.

    ``node_authorship`` is dropped, so the node dicts are the only author data left.
    """
    stored_author_id = member_only.id if request.param == "other-user" else UNKNOWN_USER_ID
    version = GraphVersioningService().save_version(graph=source_flow, name="v1")
    for node_data in version.snapshot["nodes"]:
        node_data[AUTHOR_KEY] = stored_author_id
    del version.snapshot["node_authorship"]
    version.save(update_fields=["snapshot"])
    return version


@pytest.mark.django_db
def test_version_restore_ignores_author_stored_in_snapshot_and_leaves_nodes_unauthored(
    client_as, admin_acme, acme, source_flow, version_with_node_authors
):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = _restore(client, version_with_node_authors, source_flow)

    assert response.status_code == status.HTTP_200_OK, response.content
    node_authors = _node_authors(source_flow)
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {None}


@pytest.mark.django_db
def test_graph_from_version_ignores_author_stored_in_snapshot(
    client_as, admin_acme, acme, version_with_node_authors
):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(
        reverse("graph-versions-create-graph", args=[version_with_node_authors.id])
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    node_authors = _node_authors(Graph.objects.get(pk=response.data["graph_id"]))
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {admin_acme.id}


# ---- copy authors the duplicate with the acting user ----


@pytest.mark.django_db
def test_graph_copy_is_authored_with_acting_user(client_as, admin_acme, acme, source_flow):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(reverse("graphs-copy", args=[source_flow.id]), {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    copied_graph = Graph.objects.get(pk=response.data["id"])
    assert copied_graph.created_by_id == admin_acme.id
    node_authors = _node_authors(copied_graph)
    assert len(node_authors) == len(NODE_RELATIONS)
    assert set(node_authors.values()) == {admin_acme.id}


@pytest.mark.django_db
@pytest.mark.parametrize(
    "acting_user", [None, SystemServicePrincipal()], ids=["no-user", "system-principal"]
)
def test_graph_copy_without_a_real_user_is_unauthored(source_flow, acting_user):
    copied_graph = GraphCopyService().copy(source_flow, user=acting_user)

    assert copied_graph.created_by_id is None
    assert set(_node_authors(copied_graph).values()) == {None}


@pytest.mark.django_db
def test_python_code_tool_copy_is_authored_with_acting_user(client_as, admin_acme, member_only, acme):
    tool = PythonCodeTool.objects.create(
        name="authored tool",
        description="description",
        python_code=_python_code(),
        org=acme,
        created_by=member_only,
    )
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(f"/api/python-code-tool/{tool.id}/copy/", {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert PythonCodeTool.objects.get(pk=response.data["id"]).created_by_id == admin_acme.id


@pytest.mark.django_db
def test_mcp_tool_copy_is_authored_with_acting_user(client_as, admin_acme, member_only, acme):
    tool = McpTool.objects.create(
        name="authored mcp",
        transport="https://mcp.example.com/sse",
        tool_name="search",
        org=acme,
        created_by=member_only,
    )
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    response = client.post(f"/api/mcp-tools/{tool.id}/copy/", {}, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert McpTool.objects.get(pk=response.data["id"]).created_by_id == admin_acme.id
