"""Storage grants across copy, export/import, partial import and version snapshots.

Every path that carries a flow's nodes keeps the grant flags, reads a flag that an old
file or version does not carry as ticked, lowers the ones the acting user may not hand out,
and a version restore needs every box of the flow it replaces. Exercised over HTTP with the
real services.
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
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    Edge,
    FileExtractorNode,
    PythonNode,
    StartNode,
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
    ClassificationDecisionTableNode,
)


LIST_KEYS = {
    "PythonNode": "python_node_list",
    "WebhookTriggerNode": "webhook_trigger_node_list",
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
def file_nodes_flow(acme):
    """A flow whose only content is a File Extractor and an Audio to Text node."""
    graph = Graph.objects.create(name="file-nodes-flow", org=acme)
    StartNode.objects.create(graph=graph, variables={})
    FileExtractorNode.objects.create(graph=graph)
    AudioTranscriptionNode.objects.create(graph=graph)
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
    flags = {value for rows in original.values() for row in rows for _, value in row}
    assert flags == {True, False}, "the flow must hold ticked and unticked boxes"


@pytest.mark.django_db
@pytest.mark.parametrize("path", list(PATHS))
def test_flags_the_user_may_not_hand_out_are_lowered(
    path, source, target, no_files_client
):
    result = PATHS[path](no_files_client, source, target)

    state = _flag_state(result)
    flags = [value for rows in state.values() for row in rows for _, value in row]
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


def _without_grant_keys(data: dict) -> dict:
    """The export `data` as a file written before grants existed would hold it."""
    for graph_data in data[EntityType.GRAPH]:
        for node_data in graph_data["nodes"]:
            for key in [key for key in node_data if "storage_grant_" in key]:
                del node_data[key]
    return data


def _import_legacy_file(client, graph):
    response = client.post(
        reverse("graphs-import-entity"),
        {
            "file": data_to_json_file(
                data=_without_grant_keys(_export(graph)), filename="legacy.json"
            )
        },
        format="multipart",
    )
    assert response.status_code == status.HTTP_200_OK, response.content
    return Graph.objects.latest("pk")


@pytest.mark.django_db
def test_an_old_export_without_grant_keys_reads_as_ticked_then_capped(
    source, make_files_client, admin_client
):
    reader = make_files_client(Permission.READ)

    by_admin = _import_legacy_file(admin_client, source)
    by_reader = _import_legacy_file(reader, source)

    assert [
        (n.storage_grant_read, n.storage_grant_write, n.storage_grant_delete)
        for n in by_admin.python_node_list.all()
    ] == [(True, True, True)] * 2
    assert [
        (n.storage_grant_read, n.storage_grant_write, n.storage_grant_delete)
        for n in by_reader.python_node_list.all()
    ] == [(True, False, False)] * 2


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
    assert sorted(
        (node["storage_grant_read"], node["storage_grant_write"], node["storage_grant_delete"])
        for node in response.data["python_node_list"]
    ) == [(False, False, False), (True, False, False)]
    cdt = response.data["classification_decision_table_node_list"][0]
    assert (cdt["pre_storage_grant_read"], cdt["post_storage_grant_read"]) == (True, False)


@pytest.mark.django_db
def test_restoring_a_version_needs_every_box_the_flow_has_ticked(
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


@pytest.fixture
def legacy_flow(acme):
    legacy = Graph.objects.create(name="legacy-flow", org=acme)
    StartNode.objects.create(graph=legacy, variables={})
    PythonNode.objects.create(graph=legacy, python_code=_code())
    return legacy


@pytest.mark.django_db
def test_a_version_from_before_grants_restores_for_a_partial_holder_with_the_boxes_capped(
    legacy_flow, make_files_client
):
    version = GraphVersioningService().save_version(graph=legacy_flow, name="legacy")
    for node_data in version.snapshot["nodes"]:
        for key in [key for key in node_data if "storage_grant_" in key]:
            del node_data[key]
    version.save(update_fields=["snapshot"])
    member_like = make_files_client(Permission.READ | Permission.CREATE | Permission.UPDATE)

    response = _restore(member_like, version, legacy_flow)

    assert response.status_code == status.HTTP_200_OK, response.content
    node = PythonNode.objects.get(graph=legacy_flow)
    assert (node.storage_grant_read, node.storage_grant_write, node.storage_grant_delete) == (
        True,
        True,
        False,
    )


# ---- file nodes: Files: Read to create them, on every path that carries a flow ----


FILE_NODES_NEED_READ = (
    "Creating or changing a node that reads the flow's files requires Files: Read, "
    "which you don't have. Contact an admin to change it."
)


def _file_node_counts(graph) -> tuple[int, int]:
    return graph.file_extractor_node_list.count(), graph.audio_transcription_node_list.count()


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["copy", "export_import", "create_from_version"])
def test_a_flow_with_file_nodes_needs_files_read_to_copy_import_or_branch_from_a_version(
    path, file_nodes_flow, target, no_files_client, make_files_client
):
    reader = make_files_client(Permission.READ)
    flows_before = Graph.objects.count()

    refused_by = None
    try:
        PATHS[path](no_files_client, file_nodes_flow, target)
    except AssertionError as error:
        refused_by = str(error)
    result = PATHS[path](reader, file_nodes_flow, target)

    assert refused_by is not None and "403" in refused_by
    assert "Files: Read" in refused_by
    assert _file_node_counts(result) == (1, 1)
    assert Graph.objects.count() == flows_before + 1


@pytest.mark.django_db
def test_a_partial_import_of_file_nodes_needs_files_read(
    file_nodes_flow, target, no_files_client, make_files_client
):
    reader = make_files_client(Permission.READ)
    refs = [
        NodeRef(entity_type=EntityType.FILE_EXTRACTOR_NODE, node_id=n.pk)
        for n in file_nodes_flow.file_extractor_node_list.all()
    ]
    result = GraphPartialExportService(entity_registry).export(
        refs, org_id=file_nodes_flow.org_id, policy=UNRESTRICTED_EXPORT_POLICY
    )
    url = reverse("graphs-partial-import", args=[target.id])

    def attempt(client):
        return client.post(
            url,
            {"file": data_to_json_file(data=result.data, filename="nodes.json")},
            format="multipart",
        )

    refused = attempt(no_files_client)
    allowed = attempt(reader)

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == FILE_NODES_NEED_READ
    assert allowed.status_code == status.HTTP_200_OK, allowed.content


@pytest.mark.django_db
def test_restoring_a_version_with_file_nodes_needs_files_read(
    file_nodes_flow, no_files_client, make_files_client
):
    version = GraphVersioningService().save_version(graph=file_nodes_flow, name="files")
    reader = make_files_client(Permission.READ)

    refused = _restore(no_files_client, version, file_nodes_flow)
    allowed = _restore(reader, version, file_nodes_flow)

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == FILE_NODES_NEED_READ
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert _file_node_counts(file_nodes_flow) == (1, 1)


@pytest.mark.django_db
def test_a_refused_restore_leaves_the_file_nodes_in_place(file_nodes_flow, no_files_client):
    version = GraphVersioningService().save_version(graph=file_nodes_flow, name="files")

    _restore(no_files_client, version, file_nodes_flow)

    assert _file_node_counts(file_nodes_flow) == (1, 1)
