"""Storage grants across copy, export/import, partial import and version snapshots.

Every path that carries a flow's nodes keeps the grant flags (NULL stays NULL), lowers
the ones the acting user may not hand out, and a version restore needs every grant it
applies or discards. Exercised over HTTP with the real services.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.graph_versioning.services import GraphVersioningService
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    Edge,
    FileExtractorNode,
    PythonNode,
    StartNode,
    TaskNode,
    WebhookTriggerNode,
)
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.helpers import UNRESTRICTED_EXPORT_POLICY, data_to_json_file
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ALL_PERMISSIONS = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE | Permission.USE
ALL_THREE_MESSAGE = (
    "This code runs with Files: Read, Files: Create, Files: Update, Files: Delete, which you don't have. "
    "Contact an admin to change it."
)


def _flags(prefix, values):
    names = [f"{prefix}storage_grant_{action}" for action in ("read", "write", "delete")]
    return dict(zip(names, values, strict=True))


def _code():
    return PythonCode.objects.create(code="def main(): return 1", entrypoint="main")


MODELS = (
    PythonNode,
    WebhookTriggerNode,
    FileExtractorNode,
    AudioTranscriptionNode,
    AgentNode,
    TaskNode,
    ClassificationDecisionTableNode,
)


LIST_KEYS = {
    "PythonNode": "python_node_list",
    "WebhookTriggerNode": "webhook_trigger_node_list",
    "FileExtractorNode": "file_extractor_node_list",
    "AudioTranscriptionNode": "audio_transcription_node_list",
    "AgentNode": "agent_node_list",
    "TaskNode": "task_node_list",
    "ClassificationDecisionTableNode": "classification_decision_table_node_list",
}


def _flag_state(graph) -> dict:
    """Every grant flag of the flow, per model, in a form that does not depend on node ids.

    `graph` is a Graph, or the `content` of a partial import (nothing of which is stored).
    """
    state = {}
    for model in MODELS:
        columns = sorted(field.name for field in model._meta.fields if "storage_grant_" in field.name)
        if isinstance(graph, dict):
            rows = [[node[name] for name in columns] for node in graph[LIST_KEYS[model.__name__]]]
        else:
            rows = model.objects.filter(graph=graph).values_list(*columns)
        state[model.__name__] = sorted(
            (tuple(zip(columns, row, strict=True)) for row in rows), key=repr
        )
    return state


@pytest.fixture
def source(acme):
    graph = Graph.objects.create(name="granted-flow", org=acme)
    start = StartNode.objects.create(graph=graph, variables={})
    nodes = [
        PythonNode.objects.create(graph=graph, python_code=_code(), **_flags("", (True, False, False))),
        PythonNode.objects.create(graph=graph, python_code=_code()),
        WebhookTriggerNode.objects.create(
            graph=graph, node_name="hook", python_code=_code(), **_flags("", (False, True, False))
        ),
        FileExtractorNode.objects.create(graph=graph, **_flags("", (False, False, True))),
        AudioTranscriptionNode.objects.create(graph=graph, **_flags("", (True, True, False))),
        AgentNode.objects.create(graph=graph, **_flags("", (True, False, True))),
        TaskNode.objects.create(graph=graph, **_flags("", (False, True, True))),
        ClassificationDecisionTableNode.objects.create(
            graph=graph,
            pre_python_code=_code(),
            post_python_code=_code(),
            **_flags("pre_", (True, True, True)),
            **_flags("post_", (False, False, False)),
        ),
    ]
    Edge.objects.create(graph=graph, start_node_id=start.pk, end_node_id=nodes[0].pk)
    return graph


@pytest.fixture
def target(acme):
    graph = Graph.objects.create(name="target-flow", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    return graph


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def no_files_client(client_as, custom_role_user, acme):
    permissions = {
        ResourceType.FLOWS: ALL_PERMISSIONS,
        ResourceType.WEBHOOKS: ALL_PERMISSIONS,
        ResourceType.TOOLS: Permission.CREATE | Permission.READ,
        ResourceType.AUDIT: Permission.READ,
    }
    client = client_as(custom_role_user(acme, "nofiles-flow@example.com", permissions))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _copy(client, graph):
    response = client.post(reverse("graphs-copy", args=[graph.id]), {}, format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.content
    return Graph.objects.get(pk=response.data["id"])


def _export(graph):
    return (
        ExportService(entity_registry)
        .export_entities(
            EntityType.GRAPH, [graph.id], org_id=graph.org_id, policy=UNRESTRICTED_EXPORT_POLICY
        )
        .data
    )


def _import(client, graph):
    response = client.post(
        reverse("graphs-import-entity"),
        {"file": data_to_json_file(data=_export(graph), filename="flow.json")},
        format="multipart",
    )
    assert response.status_code == status.HTTP_200_OK, response.content
    return Graph.objects.get(pk=response.data["id"]) if "id" in response.data else Graph.objects.latest("pk")


def _partial_import(client, source, target):
    refs = [
        NodeRef(entity_type=entity_type, node_id=node.pk)
        for entity_type, node in (
            (EntityType.PYTHON_NODE, source.python_node_list.all()),
            (EntityType.WEBHOOK_TRIGGER_NODE, source.webhook_trigger_node_list.all()),
            (EntityType.FILE_EXTRACTOR_NODE, source.file_extractor_node_list.all()),
            (EntityType.AUDIO_TRANSCRIPTION_NODE, source.audio_transcription_node_list.all()),
            (EntityType.AGENT_NODE, source.agent_node_list.all()),
            (EntityType.TASK_NODE, source.task_node_list.all()),
            (
                EntityType.CLASSIFICATION_DECISION_TABLE_NODE,
                source.classification_decision_table_node_list.all(),
            ),
        )
        for node in node
    ]
    result = GraphPartialExportService(entity_registry).export(
        refs, org_id=source.org_id, policy=UNRESTRICTED_EXPORT_POLICY
    )
    assert not result.has_errors, result.errors
    response = client.post(
        reverse("graphs-partial-import", args=[target.id]),
        {"file": data_to_json_file(data=result.data, filename="nodes.json")},
        format="multipart",
    )
    assert response.status_code == status.HTTP_200_OK, response.content
    return response.data["content"]


def _create_from_version(client, source):
    version = GraphVersioningService().save_version(graph=source, name="v1")
    response = client.post(reverse("graph-versions-create-graph", args=[version.id]), format="json")
    assert response.status_code == status.HTTP_201_CREATED, response.content
    return Graph.objects.get(pk=response.data["graph_id"])


def _restore(client, version, graph):
    graph.refresh_from_db()
    return client.post(
        reverse("graph-versions-restore", args=[version.id]),
        {"save_version": graph.save_version},
        format="json",
    )


PATHS = {
    "copy": lambda client, source, target: _copy(client, source),
    "export_import": lambda client, source, target: _import(client, source),
    "partial_import": lambda client, source, target: _partial_import(client, source, target),
    "create_from_version": lambda client, source, target: _create_from_version(client, source),
}


@pytest.mark.django_db
@pytest.mark.parametrize("path", list(PATHS))
def test_every_flag_survives_every_path_when_the_user_may_hand_it_out(
    path, source, target, admin_client
):
    original = _flag_state(source)

    result = PATHS[path](admin_client, source, target)

    assert _flag_state(result) == original
    assert any(
        value is None for rows in original.values() for row in rows for _, value in row
    ), "the flow must hold a not configured node for this to prove NULL stays NULL"


@pytest.mark.django_db
@pytest.mark.parametrize("path", list(PATHS))
def test_flags_the_user_may_not_hand_out_are_lowered_and_a_not_configured_slot_is_not_left_open(
    path, source, target, no_files_client
):
    result = PATHS[path](no_files_client, source, target)

    state = _flag_state(result)
    flags = [value for rows in state.values() for row in rows for _, value in row]
    # A not configured node runs with every action, so a user who may hand out none of
    # them cannot leave one behind: it becomes explicit and all off.
    assert set(flags) == {False}


@pytest.mark.django_db
def test_a_partial_import_lowers_only_what_the_user_lacks(
    source, target, make_files_client
):
    reader = make_files_client(Permission.READ)

    content = _partial_import(reader, source, target)

    state = _flag_state(content)
    kept = {name for row in state["PythonNode"] for name, value in row if value}
    assert kept == {"storage_grant_read"}
    assert {name for rows in state.values() for row in rows for name, value in row if value} == {
        "storage_grant_read",
        "pre_storage_grant_read",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["copy", "export_import"])
def test_a_not_configured_node_becomes_what_a_partial_holder_may_hand_out(
    path, source, target, make_files_client
):
    reader = make_files_client(Permission.READ)

    result = PATHS[path](reader, source, target)

    unconfigured = [
        node
        for node in result.python_node_list.all()
        if not node.storage_grant_write and not node.storage_grant_delete
    ]
    assert (True, False, False) in [
        (n.storage_grant_read, n.storage_grant_write, n.storage_grant_delete) for n in unconfigured
    ]
    assert not PythonNode.objects.filter(
        graph=result, storage_grant_read__isnull=True
    ).exists()


@pytest.fixture
def make_files_client(client_as, custom_role_user, acme):
    made = []

    def _make(files):
        made.append(files)
        permissions = {
            ResourceType.FLOWS: ALL_PERMISSIONS,
            ResourceType.WEBHOOKS: ALL_PERMISSIONS,
            ResourceType.TOOLS: Permission.CREATE | Permission.READ,
            ResourceType.AUDIT: Permission.READ,
            ResourceType.FILES: files,
        }
        client = client_as(custom_role_user(acme, f"files-flow-{len(made)}@example.com", permissions))
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.mark.django_db
def test_the_grants_are_loaded_with_the_flow(source, admin_client):
    response = admin_client.get(reverse("graphs-detail", args=[source.id]))

    assert response.status_code == status.HTTP_200_OK
    python_nodes = response.data["python_node_list"]
    assert sorted(
        (node["storage_grant_read"], node["storage_grant_write"], node["storage_grant_delete"])
        for node in python_nodes
        if node["storage_grant_read"] is not None
    ) == [(True, False, False)]
    assert any(node["storage_grant_read"] is None for node in python_nodes)
    cdt = response.data["classification_decision_table_node_list"][0]
    assert (cdt["pre_storage_grant_read"], cdt["post_storage_grant_read"]) == (True, False)
    assert response.data["agent_node_list"][0]["storage_grant_delete"] is True


@pytest.mark.django_db
def test_restoring_a_version_needs_every_grant_it_applies_and_discards(
    source, admin_client, no_files_client
):
    version = GraphVersioningService().save_version(graph=source, name="v1")
    before = _flag_state(source)

    refused = _restore(no_files_client, version, source)
    allowed = _restore(admin_client, version, source)

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["message"] == ALL_THREE_MESSAGE
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert _flag_state(source) == before


@pytest.mark.django_db
def test_restoring_over_a_flow_whose_current_grants_the_user_lacks_is_refused(
    source, acme, no_files_client
):
    plain = Graph.objects.create(name="plain-flow", org=acme)
    StartNode.objects.create(graph=plain, variables={})
    PythonNode.objects.create(graph=plain, python_code=_code(), **_flags("", (False, False, False)))
    version = GraphVersioningService().save_version(graph=plain, name="plain")
    PythonNode.objects.filter(graph=plain).update(**_flags("", (False, True, False)))

    response = _restore(no_files_client, version, plain)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "Files: Create, Files: Update" in response.data["message"]
    assert PythonNode.objects.get(graph=plain).storage_grant_write is True


@pytest.mark.django_db
def test_another_orgs_version_is_a_404_before_any_grant_check(
    source, beta, client_as, custom_role_user
):
    version = GraphVersioningService().save_version(graph=source, name="v1")
    outsider = client_as(
        custom_role_user(beta, "outsider-flow@example.com", {ResourceType.FLOWS: ALL_PERMISSIONS})
    )
    outsider.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = _restore(outsider, version, source)

    assert response.status_code == status.HTTP_404_NOT_FOUND


ALL_FILES = Permission.READ | Permission.CREATE | Permission.UPDATE | Permission.DELETE


@pytest.fixture
def legacy_flow(acme):
    legacy = Graph.objects.create(name="legacy-flow", org=acme)
    StartNode.objects.create(graph=legacy, variables={})
    PythonNode.objects.create(graph=legacy, python_code=_code())
    return legacy


@pytest.mark.django_db
def test_restoring_not_configured_over_not_configured_needs_no_files_grant(
    legacy_flow, make_files_client
):
    version = GraphVersioningService().save_version(graph=legacy_flow, name="legacy")
    reader = make_files_client(Permission.READ)

    response = _restore(reader, version, legacy_flow)

    assert response.status_code == status.HTTP_200_OK, response.content
    node = PythonNode.objects.get(graph=legacy_flow)
    assert (node.storage_grant_read, node.storage_grant_write, node.storage_grant_delete) == (
        None,
        None,
        None,
    )


@pytest.mark.django_db
def test_restoring_not_configured_over_an_explicit_slot_needs_all_three_grants(
    legacy_flow, make_files_client
):
    version = GraphVersioningService().save_version(graph=legacy_flow, name="legacy")
    PythonNode.objects.filter(graph=legacy_flow).update(**_flags("", (True, False, False)))
    reader = make_files_client(Permission.READ)
    everything = make_files_client(ALL_FILES)

    refused = _restore(reader, version, legacy_flow)
    allowed = _restore(everything, version, legacy_flow)

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["code"] == "storage_grant_denied"
    assert refused.data["message"] == (
        "This code runs with Files: Create, Files: Update, Files: Delete, which you don't have. "
        "Contact an admin to change it."
    )
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert PythonNode.objects.get(graph=legacy_flow).storage_grant_read is None


@pytest.mark.django_db
def test_restoring_not_configured_over_an_explicit_node_added_since_needs_no_extra_grant(
    legacy_flow, make_files_client
):
    version = GraphVersioningService().save_version(graph=legacy_flow, name="legacy")
    PythonNode.objects.create(
        graph=legacy_flow, python_code=_code(), **_flags("", (False, False, False))
    )
    reader = make_files_client(Permission.READ)

    response = _restore(reader, version, legacy_flow)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_restoring_not_configured_over_an_explicit_slot_is_matched_per_node(
    legacy_flow, make_files_client
):
    other = PythonNode.objects.create(
        graph=legacy_flow, python_code=_code(), **_flags("", (False, False, False))
    )
    version = GraphVersioningService().save_version(graph=legacy_flow, name="two-nodes")
    PythonNode.objects.filter(pk=other.pk).update(storage_grant_read=None, storage_grant_write=None, storage_grant_delete=None)
    PythonNode.objects.exclude(pk=other.pk).update(**_flags("", (False, False, False)))
    reader = make_files_client(Permission.READ)

    response = _restore(reader, version, legacy_flow)

    # The version holds the legacy node's slot as not configured, and the flow now has an
    # explicit slot on that same node (same number), so the restore widens it.
    assert response.status_code == status.HTTP_403_FORBIDDEN
