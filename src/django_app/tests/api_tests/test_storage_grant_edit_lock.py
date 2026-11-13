"""The edit rule of per-node storage grants.

Python code holds the storage account its node's boxes allow, so editing a node needs the
Files permissions behind what it grants. Per grant slot of a node:

1. Raising a box needs that box's Files permissions.
2. Changing what the code does needs every box the node currently has ticked.
3. Lowering a box is always allowed.
4. File Extractor and Audio to Text have no boxes: creating one or changing a field of it
   needs Files: Read, deleting one needs nothing.

Every path that writes a node is exercised over HTTP, for every model that carries grants.
"""

from dataclasses import dataclass, field

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
    WebhookTriggerNode,
)
from tables.services.storage_grants.slots import FILE_NODE_MODELS, STORAGE_GRANT_SLOTS
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ALL_THREE = "This code runs with Files: Read, Files: Create, Files: Update, Files: Delete, which you don't have. Contact an admin to change it."
READ_ONLY_MESSAGE = "This code runs with Files: Read, which you don't have. Contact an admin to change it."
FILE_NODE_MESSAGE = "Creating or changing a node that reads the flow's files requires Files: Read, which you don't have. Contact an admin to change it."
DELETE_ONLY = "Changing the files this code can access requires Files: Delete, which you don't have. Contact an admin to change it."
FLOWS_ALL = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE | Permission.USE
CODE = {"code": "def main(): return 1", "entrypoint": "main"}
OTHER_CODE = {"code": "def main(): return 2", "entrypoint": "main"}


@dataclass(frozen=True)
class Kind:
    name: str
    model: type
    list_key: str
    url: str
    make: object
    steer: dict
    bulk_base: dict = field(default_factory=dict)
    prefix: str = ""
    boxes: tuple[str, ...] = ("read", "write", "delete")
    """The grant boxes of the node: none for File Extractor and Audio to Text."""


def _code():
    return PythonCode.objects.create(**CODE)


def _flags(prefix, values, boxes=("read", "write", "delete")):
    names = [f"{prefix}storage_grant_{box}" for box in boxes]
    return dict(zip(names, values, strict=True))


KINDS = [
    Kind(
        "python",
        PythonNode,
        "python_node_list",
        "/api/pythonnodes/",
        lambda graph, flags: PythonNode.objects.create(graph=graph, python_code=_code(), **flags),
        {"input_map": {"a": "variables.b"}},
        {"python_code": CODE},
    ),
    Kind(
        "webhook",
        WebhookTriggerNode,
        "webhook_trigger_node_list",
        "/api/webhook-trigger-nodes/",
        lambda graph, flags: WebhookTriggerNode.objects.create(
            graph=graph, node_name="hook", python_code=_code(), **flags
        ),
        {"use_storage": True},
        {"node_name": "hook", "python_code": CODE, "metadata": {}},
    ),
    Kind(
        "file_extractor",
        FileExtractorNode,
        "file_extractor_node_list",
        "/api/file-extractor-nodes/",
        lambda graph, flags: FileExtractorNode.objects.create(graph=graph, **flags),
        {"input_map": {"a": "variables.b"}},
        boxes=(),
    ),
    Kind(
        "audio",
        AudioTranscriptionNode,
        "audio_transcription_node_list",
        "/api/audio-transcription-nodes/",
        lambda graph, flags: AudioTranscriptionNode.objects.create(graph=graph, **flags),
        {"input_map": {"a": "variables.b"}},
        boxes=(),
    ),
    Kind(
        "classification_pre",
        ClassificationDecisionTableNode,
        "classification_decision_table_node_list",
        "/api/classification-decision-table-node/",
        lambda graph, flags: ClassificationDecisionTableNode.objects.create(
            graph=graph, pre_python_code=_code(), post_python_code=_code(), **flags
        ),
        {"pre_input_map": {"a": "variables.b"}},
        prefix="pre_",
    ),
]
KIND_IDS = [kind.name for kind in KINDS]
THREE_BOX_KINDS = [kind for kind in KINDS if len(kind.boxes) == 3]
FILE_KINDS = [kind for kind in KINDS if kind.boxes == ()]
PYTHON = KINDS[0]


def test_every_model_that_carries_grants_or_reads_files_has_a_kind_in_this_suite():
    assert {kind.model for kind in KINDS} == set(STORAGE_GRANT_SLOTS) | set(FILE_NODE_MODELS)


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="grant-flow", org=acme)


@pytest.fixture
def make_client(client_as, custom_role_user, acme):
    def _make(email, files):
        permissions = {ResourceType.FLOWS: FLOWS_ALL}
        if files:
            permissions[ResourceType.FILES] = files
        client = client_as(custom_role_user(acme, email, permissions))
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.fixture
def viewer_client(client_as, custom_role_user, acme):
    """A custom role that may update and use flows and has no Files permission at all."""
    permissions = {ResourceType.FLOWS: Permission.READ | Permission.UPDATE | Permission.USE}
    client = client_as(custom_role_user(acme, "viewer-flows@example.com", permissions))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def no_files_client(make_client):
    """May create, edit and use flows, and has no Files permission at all."""
    return make_client("nofiles@example.com", None)


@pytest.fixture
def read_client(make_client):
    return make_client("reader@example.com", Permission.READ)


@pytest.fixture
def member_client(client_as, member_only, acme):
    """The built-in Member role: Files create, read, update and export, but not delete."""
    client = client_as(member_only)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _granted(kind, ticked=True):
    return _flags(kind.prefix, (ticked,) * len(kind.boxes), kind.boxes)


def _patch(client, kind, node, body):
    return client.patch(f"{kind.url}{node.pk}/", body, format="json")


def _bulk(client, kind, graph, node, fields):
    graph.refresh_from_db()
    item = {"id": node.pk, "graph": graph.pk, **kind.bulk_base, **fields}
    return client.post(
        reverse("graphs-save-flow", args=[graph.pk]),
        {"save_version": graph.save_version, kind.list_key: [item]},
        format="json",
    )


def _stored(node, name):
    return getattr(type(node).objects.get(pk=node.pk), name)


def _steer(entry, client, kind, flow, node):
    if entry == "viewset":
        return _patch(client, kind, node, kind.steer)
    return _bulk(client, kind, flow, node, kind.steer)


# ---- rule 2: changing what a ticked node's code does ------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize("kind", THREE_BOX_KINDS, ids=lambda kind: kind.name)
def test_steering_a_node_needs_every_box_it_has_ticked(
    kind, entry, flow, viewer_client, read_client, admin_client
):
    node = kind.make(flow, _granted(kind))
    (field_name, value), *_ = kind.steer.items()

    refused = _steer(entry, viewer_client, kind, flow, node)
    partly = _steer(entry, read_client, kind, flow, node)
    # The same write by someone holding every ticked box goes through.
    allowed = _steer(entry, admin_client, kind, flow, node)

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == ALL_THREE
    assert refused.data["missing_grants"] == ["read", "write", "delete"]
    assert partly.status_code == status.HTTP_403_FORBIDDEN
    assert partly.data["missing_grants"] == ["write", "delete"]
    assert allowed.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), allowed.content
    assert _stored(node, field_name) == value


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_refused_steering_write_changes_nothing(kind, flow, viewer_client):
    node = kind.make(flow, _granted(kind))
    (field_name, value), *_ = kind.steer.items()
    before = _stored(node, field_name)

    response = _patch(viewer_client, kind, node, kind.steer)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert _stored(node, field_name) == before != value


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize("kind", THREE_BOX_KINDS, ids=lambda kind: kind.name)
def test_a_node_with_no_box_ticked_is_not_locked(kind, entry, flow, viewer_client):
    node = kind.make(flow, _granted(kind, ticked=False))

    response = _steer(entry, viewer_client, kind, flow, node)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_member_cannot_change_code_while_delete_ticked(flow, member_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, True))
    )

    response = _patch(member_client, PYTHON, node, {"python_code": OTHER_CODE})

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["message"] == (
        "This code runs with Files: Delete, which you don't have. Contact an admin to change it."
    )
    assert PythonCode.objects.get(pk=node.python_code_id).code == CODE["code"]


@pytest.mark.django_db
def test_member_can_change_code_when_every_ticked_box_is_one_they_hold(flow, member_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, False))
    )

    response = _patch(member_client, PYTHON, node, {"python_code": OTHER_CODE})

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_the_nested_code_is_locked_but_an_unchanged_resend_is_not(flow, viewer_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, False, False))
    )

    unchanged = _patch(viewer_client, PYTHON, node, {"python_code": CODE})
    edited = _patch(viewer_client, PYTHON, node, {"python_code": OTHER_CODE})

    assert unchanged.status_code == status.HTTP_200_OK
    assert edited.status_code == status.HTTP_403_FORBIDDEN
    assert edited.data["message"] == READ_ONLY_MESSAGE


@pytest.mark.django_db
def test_each_code_slot_of_a_classification_table_is_locked_by_its_own_boxes(
    flow, viewer_client
):
    node = ClassificationDecisionTableNode.objects.create(
        graph=flow,
        pre_python_code=_code(),
        post_python_code=_code(),
        **_flags("pre_", (False, False, False)),
        **_flags("post_", (True, False, False)),
    )
    url = "/api/classification-decision-table-node/"

    pre = viewer_client.patch(f"{url}{node.pk}/", {"pre_input_map": {"a": "b"}}, format="json")
    post = viewer_client.patch(f"{url}{node.pk}/", {"post_input_map": {"a": "b"}}, format="json")

    assert pre.status_code == status.HTTP_200_OK
    assert post.status_code == status.HTTP_403_FORBIDDEN
    assert post.data["message"] == READ_ONLY_MESSAGE


# ---- rule 1: raising a box ---------------------------------------------------


@pytest.mark.django_db
def test_member_cannot_tick_delete(flow, member_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    response = _patch(member_client, PYTHON, node, {"storage_grant_delete": True})

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["message"] == DELETE_ONLY
    assert PythonNode.objects.get(pk=node.pk).storage_grant_delete is False


@pytest.mark.django_db
def test_member_can_tick_read_and_write(flow, member_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    response = _patch(
        member_client, PYTHON, node, {"storage_grant_read": True, "storage_grant_write": True}
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    stored = PythonNode.objects.get(pk=node.pk)
    assert (stored.storage_grant_read, stored.storage_grant_write) == (True, True)


@pytest.mark.django_db
def test_raising_a_box_needs_its_permission(flow, viewer_client, read_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    refused = _patch(viewer_client, PYTHON, node, {"storage_grant_read": True})
    allowed = _patch(read_client, PYTHON, node, {"storage_grant_read": True})
    too_much = _patch(read_client, PYTHON, node, {"storage_grant_write": True})

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["message"] == (
        "Changing the files this code can access requires Files: Read, which you don't have. "
        "Contact an admin to change it."
    )
    assert allowed.status_code == status.HTTP_200_OK
    assert too_much.status_code == status.HTTP_403_FORBIDDEN
    assert "Files: Create, Files: Update" in too_much.data["message"]
    stored = PythonNode.objects.get(pk=node.pk)
    assert (stored.storage_grant_read, stored.storage_grant_write) == (True, False)


@pytest.mark.django_db
def test_write_needs_both_create_and_update(flow, make_client):
    create_only = make_client("create-only@example.com", Permission.READ | Permission.CREATE)
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    response = _patch(create_only, PYTHON, node, {"storage_grant_write": True})

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["missing_grants"] == ["write"]
    assert "requires Files: Update, which" in response.data["message"]


@pytest.mark.django_db
def test_raising_a_box_and_changing_code_needs_both(flow, member_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (False, False, False))
    )

    response = _patch(
        member_client,
        PYTHON,
        node,
        {"storage_grant_delete": True, "python_code": OTHER_CODE},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert PythonNode.objects.get(pk=node.pk).storage_grant_delete is False


# ---- rule 3: lowering a box ---------------------------------------------------


@pytest.mark.django_db
def test_member_can_untick_delete_on_admin_node(flow, member_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, True))
    )

    response = _patch(member_client, PYTHON, node, {"storage_grant_delete": False})

    assert response.status_code == status.HTTP_200_OK, response.content
    stored = PythonNode.objects.get(pk=node.pk)
    assert stored.storage_grant_delete is False
    assert (stored.storage_grant_read, stored.storage_grant_write) == (True, True)


@pytest.mark.django_db
def test_member_untick_and_change_code_in_one_request_is_refused(flow, member_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, True))
    )

    response = _patch(
        member_client,
        PYTHON,
        node,
        {"storage_grant_delete": False, "python_code": OTHER_CODE},
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    stored = PythonNode.objects.get(pk=node.pk)
    assert stored.storage_grant_delete is True
    assert PythonCode.objects.get(pk=stored.python_code_id).code == CODE["code"]


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
def test_member_untick_and_change_code_over_a_bulk_save_is_refused_whole(
    entry, flow, member_client
):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, True))
    )
    fields = {"storage_grant_delete": False, "python_code": OTHER_CODE}

    if entry == "viewset":
        response = _patch(member_client, PYTHON, node, fields)
    else:
        response = _bulk(member_client, PYTHON, flow, node, fields)

    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    stored = PythonNode.objects.get(pk=node.pk)
    assert stored.storage_grant_delete is True
    assert PythonCode.objects.get(pk=stored.python_code_id).code == CODE["code"]


@pytest.mark.django_db
def test_lowering_every_box_needs_no_permission(flow, viewer_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, True))
    )

    response = _patch(viewer_client, PYTHON, node, _flags("", (False, False, False)))

    assert response.status_code == status.HTTP_200_OK, response.content
    stored = PythonNode.objects.get(pk=node.pk)
    assert [stored.storage_grant_read, stored.storage_grant_write, stored.storage_grant_delete] == [
        False
    ] * 3


@pytest.mark.django_db
def test_resending_the_stored_boxes_needs_nothing(flow, viewer_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, True))
    )

    response = _patch(viewer_client, PYTHON, node, _flags("", (True, True, True)))

    assert response.status_code == status.HTTP_200_OK


# ---- a save where nothing of a slot changed is never checked ------------------


@pytest.mark.django_db
def test_member_bulk_save_of_unchanged_flow_succeeds(flow, member_client):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, True, True))
    )
    flow.refresh_from_db()
    item = {
        "id": node.pk,
        "graph": flow.pk,
        "python_code": CODE,
        "input_map": node.input_map,
        "use_storage": node.use_storage,
        **_flags("", (True, True, True)),
        "node_name": "renamed",
    }

    response = member_client.post(
        reverse("graphs-save-flow", args=[flow.pk]),
        {"save_version": flow.save_version, "python_node_list": [item]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert PythonNode.objects.get(pk=node.pk).node_name == "renamed"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", THREE_BOX_KINDS, ids=lambda kind: kind.name)
def test_the_name_and_output_path_of_a_ticked_node_are_not_locked(kind, flow, viewer_client):
    node = kind.make(flow, _granted(kind))
    body = {"output_variable_path": "variables.result"}
    if kind.model is not ClassificationDecisionTableNode:
        body["node_name"] = "renamed"

    response = _patch(viewer_client, kind, node, body)

    assert response.status_code == status.HTTP_200_OK, response.content


# ---- rule 4: file extractor and audio to text --------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize("kind", FILE_KINDS, ids=lambda kind: kind.name)
def test_user_without_files_read_cannot_update_a_file_node(
    kind, entry, flow, viewer_client, read_client
):
    node = kind.make(flow, {})

    refused = _steer(entry, viewer_client, kind, flow, node)
    allowed = _steer(entry, read_client, kind, flow, node)

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == FILE_NODE_MESSAGE
    assert refused.data["missing_grants"] == ["read"]
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert _stored(node, "input_map") == kind.steer["input_map"]


@pytest.mark.django_db
@pytest.mark.parametrize("kind", FILE_KINDS, ids=lambda kind: kind.name)
def test_a_file_node_rename_and_a_move_to_another_flow_need_files_read(
    kind, acme, flow, viewer_client, read_client
):
    other_flow = Graph.objects.create(name="other-file-flow", org=acme)
    node = kind.make(flow, {})

    renamed = _patch(viewer_client, kind, node, {"node_name": "renamed"})
    moved = _patch(viewer_client, kind, node, {"graph": other_flow.pk})
    moved_by_reader = _patch(read_client, kind, node, {"graph": other_flow.pk})

    assert renamed.status_code == status.HTTP_403_FORBIDDEN
    assert moved.status_code == status.HTTP_403_FORBIDDEN
    assert moved_by_reader.status_code == status.HTTP_200_OK, moved_by_reader.content
    assert type(node).objects.get(pk=node.pk).graph_id == other_flow.pk


@pytest.mark.django_db
@pytest.mark.parametrize("kind", FILE_KINDS, ids=lambda kind: kind.name)
def test_resending_an_unchanged_file_node_needs_nothing(kind, flow, viewer_client):
    node = kind.make(flow, {})

    viewset = _patch(viewer_client, kind, node, {"input_map": {}})
    bulk = _bulk(viewer_client, kind, flow, node, {"input_map": {}})

    assert viewset.status_code == status.HTTP_200_OK, viewset.content
    assert bulk.status_code == status.HTTP_200_OK, bulk.content


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize("kind", FILE_KINDS, ids=lambda kind: kind.name)
def test_user_without_files_read_cannot_create_a_file_node(
    kind, entry, flow, no_files_client, read_client
):
    def create(client):
        flow.refresh_from_db()
        if entry == "viewset":
            return client.post(kind.url, {"graph": flow.pk}, format="json")
        return client.post(
            reverse("graphs-save-flow", args=[flow.pk]),
            {"save_version": flow.save_version, kind.list_key: [{"graph": flow.pk}]},
            format="json",
        )

    refused = create(no_files_client)
    created_by_refused = kind.model.objects.filter(graph=flow).count()
    allowed = create(read_client)

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == FILE_NODE_MESSAGE
    assert created_by_refused == 0
    assert allowed.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), allowed.content
    assert kind.model.objects.filter(graph=flow).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize("kind", FILE_KINDS, ids=lambda kind: kind.name)
def test_user_without_files_read_can_delete_a_file_node(kind, entry, flow, no_files_client):
    node = kind.make(flow, {})

    if entry == "viewset":
        response = no_files_client.delete(f"{kind.url}{node.pk}/")
    else:
        flow.refresh_from_db()
        response = no_files_client.post(
            reverse("graphs-save-flow", args=[flow.pk]),
            {
                "save_version": flow.save_version,
                "deleted": {kind.list_key.replace("_list", "_ids"): [node.pk]},
            },
            format="json",
        )

    assert response.status_code in (status.HTTP_200_OK, status.HTTP_204_NO_CONTENT), response.content
    assert not kind.model.objects.filter(pk=node.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("kind", FILE_KINDS, ids=lambda kind: kind.name)
def test_a_file_node_has_no_grant_field(kind, flow, read_client):
    node = kind.make(flow, {})

    response = _patch(read_client, kind, node, {"storage_grant_read": True})

    assert response.status_code == status.HTTP_200_OK
    assert "storage_grant_read" not in response.data


# ---- creating nodes -----------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("kind", THREE_BOX_KINDS, ids=lambda kind: kind.name)
def test_a_node_created_without_boxes_gets_them_all_off_and_needs_no_permission(
    kind, flow, no_files_client
):
    flow.refresh_from_db()
    item = {"graph": flow.pk, **kind.bulk_base}

    response = no_files_client.post(
        reverse("graphs-save-flow", args=[flow.pk]),
        {"save_version": flow.save_version, kind.list_key: [item]},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node = kind.model.objects.get(graph=flow)
    assert [getattr(node, name) for name in _granted(kind)] == [False] * len(kind.boxes)


@pytest.mark.django_db
def test_creating_a_python_node_over_the_viewset_defaults_the_boxes_off(flow, no_files_client):
    response = no_files_client.post(
        "/api/pythonnodes/", {"graph": flow.pk, "python_code": CODE}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert [response.data[name] for name in _flags("", (0, 0, 0))] == [False] * 3


@pytest.mark.django_db
def test_creating_a_node_with_a_box_ticked_needs_the_permission(flow, no_files_client, read_client):
    body = {"graph": flow.pk, "python_code": CODE, "storage_grant_read": True}

    refused = no_files_client.post("/api/pythonnodes/", body, format="json")
    allowed = read_client.post("/api/pythonnodes/", body, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert allowed.status_code == status.HTTP_201_CREATED, allowed.content
    assert PythonNode.objects.filter(graph=flow).count() == 1


@pytest.mark.django_db
def test_a_boolean_box_cannot_be_null(flow, admin_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    response = _patch(admin_client, PYTHON, node, {"storage_grant_read": None})

    assert response.status_code == status.HTTP_400_BAD_REQUEST


# ---- org scoping and moving ----------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_another_orgs_node_is_a_404_not_a_403(kind, flow, beta, client_as, custom_role_user):
    node = kind.make(flow, _granted(kind))
    outsider = client_as(
        custom_role_user(beta, "outsider@example.com", {ResourceType.FLOWS: FLOWS_ALL})
    )
    outsider.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = _patch(outsider, kind, node, kind.steer)

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("kind", THREE_BOX_KINDS, ids=lambda kind: kind.name)
def test_moving_a_ticked_node_to_another_flow_needs_its_boxes(
    kind, acme, flow, viewer_client, admin_client
):
    other_flow = Graph.objects.create(name="other-flow", org=acme)
    node = kind.make(flow, _granted(kind))

    refused = _patch(viewer_client, kind, node, {"graph": other_flow.pk})
    stays = _patch(viewer_client, kind, node, {"graph": flow.pk})
    allowed = _patch(admin_client, kind, node, {"graph": other_flow.pk})

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["message"].startswith("This code runs with Files: Read")
    assert stays.status_code == status.HTTP_200_OK
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert type(node).objects.get(pk=node.pk).graph_id == other_flow.pk


@pytest.mark.django_db
def test_moving_a_node_with_no_box_ticked_is_free(acme, flow, viewer_client):
    other_flow = Graph.objects.create(name="other-flow-free", org=acme)
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    response = _patch(viewer_client, PYTHON, node, {"graph": other_flow.pk})

    assert response.status_code == status.HTTP_200_OK
