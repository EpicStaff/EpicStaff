"""The edit lock of per-node storage grants.

Python code holds the storage account its node's grant allows, so whoever may change the
grant, or what the code does, must hold the Files permissions behind it. Every path that
writes a node is exercised over HTTP, for every model that carries grants.
"""

from dataclasses import dataclass, field

import pytest
from django.urls import reverse
from rest_framework import status

from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
    TaskNode,
    WebhookTriggerNode,
)
from tables.services.storage_grants.slots import STORAGE_GRANT_SLOTS
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ALL_THREE = "This code runs with Files: Read, Files: Create, Files: Update, Files: Delete, which you don't have. Contact an admin to change it."
WRITE_AND_DELETE = "This code runs with Files: Create, Files: Update, Files: Delete, which you don't have. Contact an admin to change it."
FLOWS_ALL = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE | Permission.USE
CODE = {"code": "def main(): return 1", "entrypoint": "main"}


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


def _code():
    return PythonCode.objects.create(**CODE)


def _flags(prefix, values):
    names = [f"{prefix}storage_grant_{action}" for action in ("read", "write", "delete")]
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
    ),
    Kind(
        "audio",
        AudioTranscriptionNode,
        "audio_transcription_node_list",
        "/api/audio-transcription-nodes/",
        lambda graph, flags: AudioTranscriptionNode.objects.create(graph=graph, **flags),
        {"input_map": {"a": "variables.b"}},
    ),
    Kind(
        "agent",
        AgentNode,
        "agent_node_list",
        "/api/agentnodes/",
        lambda graph, flags: AgentNode.objects.create(graph=graph, **flags),
        {"input_map": {"a": "variables.b"}},
    ),
    Kind(
        "task",
        TaskNode,
        "task_node_list",
        "/api/tasknodes/",
        lambda graph, flags: TaskNode.objects.create(graph=graph, **flags),
        {"input_map": {"a": "variables.b"}},
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


def test_every_model_that_carries_grants_has_a_kind_in_this_suite():
    assert {kind.model for kind in KINDS} == set(STORAGE_GRANT_SLOTS)


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="grant-flow", org=acme)


@pytest.fixture
def make_client(client_as, custom_role_user, acme):
    def _make(email, files):
        permissions = {ResourceType.FLOWS: FLOWS_ALL, ResourceType.TOOLS: FLOWS_ALL}
        if files:
            permissions[ResourceType.FILES] = files
        client = client_as(custom_role_user(acme, email, permissions))
        client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
        return client

    return _make


@pytest.fixture
def no_files_client(make_client):
    return make_client("nofiles@example.com", None)


@pytest.fixture
def read_client(make_client):
    return make_client("reader@example.com", Permission.READ)


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _granted(kind, values=(True, True, True)):
    return _flags(kind.prefix, values)


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


def _stored(kind, node, name):
    return getattr(type(node).objects.get(pk=node.pk), name)


# ---- steering a granted node ------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_steering_a_granted_node_needs_every_granted_permission(
    kind, entry, flow, no_files_client, read_client, admin_client
):
    node = kind.make(flow, _granted(kind))
    (field_name, value), *_ = kind.steer.items()

    def attempt(client):
        if entry == "viewset":
            return _patch(client, kind, node, kind.steer)
        return _bulk(client, kind, flow, node, kind.steer)

    refused = attempt(no_files_client)
    partly = attempt(read_client)
    # The same write by someone holding every granted permission goes through.
    allowed = attempt(admin_client)

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == ALL_THREE
    assert refused.data["missing_grants"] == ["read", "write", "delete"]
    assert partly.status_code == status.HTTP_403_FORBIDDEN
    assert partly.data["message"] == WRITE_AND_DELETE
    assert allowed.status_code in (status.HTTP_200_OK, status.HTTP_201_CREATED), allowed.content
    assert _stored(kind, node, field_name) == value


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_refused_steering_write_changes_nothing(kind, flow, no_files_client):
    node = kind.make(flow, _granted(kind))
    (field_name, value), *_ = kind.steer.items()
    before = _stored(kind, node, field_name)

    response = _patch(no_files_client, kind, node, kind.steer)

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert _stored(kind, node, field_name) == before != value


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_node_without_a_grant_is_not_locked(kind, entry, flow, no_files_client):
    not_configured = kind.make(flow, {})
    granted_nothing = kind.make(flow, _granted(kind, (False, False, False)))

    for node in (not_configured, granted_nothing):
        if entry == "viewset":
            response = _patch(no_files_client, kind, node, kind.steer)
        else:
            response = _bulk(no_files_client, kind, flow, node, kind.steer)
        assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_the_nested_code_of_a_granted_node_is_locked_but_an_unchanged_resend_is_not(
    flow, no_files_client
):
    node = PythonNode.objects.create(
        graph=flow, python_code=_code(), **_flags("", (True, False, False))
    )

    unchanged = _patch(no_files_client, KINDS[0], node, {"python_code": CODE})
    edited = _patch(
        no_files_client, KINDS[0], node, {"python_code": {**CODE, "code": "def main(): return 2"}}
    )

    assert unchanged.status_code == status.HTTP_200_OK
    assert edited.status_code == status.HTTP_403_FORBIDDEN
    assert "Files: Read" in edited.data["message"]


@pytest.mark.django_db
def test_each_code_slot_of_a_classification_table_is_locked_by_its_own_grant(
    flow, no_files_client
):
    node = ClassificationDecisionTableNode.objects.create(
        graph=flow,
        pre_python_code=_code(),
        post_python_code=_code(),
        **_flags("pre_", (False, False, False)),
        **_flags("post_", (True, False, False)),
    )
    url = "/api/classification-decision-table-node/"

    pre = no_files_client.patch(f"{url}{node.pk}/", {"pre_input_map": {"a": "b"}}, format="json")
    post = no_files_client.patch(f"{url}{node.pk}/", {"post_input_map": {"a": "b"}}, format="json")

    assert pre.status_code == status.HTTP_200_OK
    assert post.status_code == status.HTTP_403_FORBIDDEN
    assert post.data["message"].startswith("This code runs with Files: Read,")


# ---- setting and clearing the flags -----------------------------------------


@pytest.mark.django_db
def test_setting_a_flag_needs_its_permission(flow, no_files_client, read_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), **_flags("", (False,) * 3))
    kind = KINDS[0]

    refused = _patch(no_files_client, kind, node, {"storage_grant_read": True})
    allowed = _patch(read_client, kind, node, {"storage_grant_read": True})
    too_much = _patch(read_client, kind, node, {"storage_grant_write": True})

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
def test_clearing_a_flag_needs_its_permission_too(flow, no_files_client, admin_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), **_flags("", (True, False, False)))
    kind = KINDS[0]

    refused = _patch(no_files_client, kind, node, {"storage_grant_read": False})
    allowed = _patch(admin_client, kind, node, {"storage_grant_read": False})

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert allowed.status_code == status.HTTP_200_OK
    assert PythonNode.objects.get(pk=node.pk).storage_grant_read is False


@pytest.mark.django_db
def test_write_needs_both_create_and_update(flow, make_client):
    create_only = make_client("create-only@example.com", Permission.READ | Permission.CREATE)
    node = PythonNode.objects.create(graph=flow, python_code=_code(), **_flags("", (False,) * 3))

    response = _patch(create_only, KINDS[0], node, {"storage_grant_write": True})

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["missing_grants"] == ["write"]
    assert "requires Files: Update, which" in response.data["message"]


@pytest.mark.django_db
def test_a_not_configured_node_counts_as_holding_every_action(flow, no_files_client, read_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    resend = _patch(no_files_client, KINDS[0], node, {"input_map": {"a": "b"}})
    lowered = _patch(read_client, KINDS[0], node, _flags("", (True, False, False)))

    assert resend.status_code == status.HTTP_200_OK
    assert lowered.status_code == status.HTTP_403_FORBIDDEN
    assert lowered.data["missing_grants"] == ["write", "delete"]


@pytest.mark.django_db
def test_resending_the_stored_flags_needs_nothing(flow, no_files_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), **_flags("", (True, True, True)))

    response = _patch(no_files_client, KINDS[0], node, _flags("", (True, True, True)))

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_sending_one_flag_saves_the_whole_slot_and_null_cannot_be_mixed(flow, admin_client):
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    partial = _patch(admin_client, KINDS[0], node, {"storage_grant_delete": True})
    mixed = _patch(admin_client, KINDS[0], node, {"storage_grant_read": None})
    cleared = _patch(admin_client, KINDS[0], node, _flags("", (None, None, None)))

    assert partial.status_code == status.HTTP_200_OK
    assert partial.data["storage_grant_read"] is False
    assert partial.data["storage_grant_delete"] is True
    assert mixed.status_code == status.HTTP_400_BAD_REQUEST
    assert cleared.status_code == status.HTTP_200_OK
    assert PythonNode.objects.get(pk=node.pk).storage_grant_read is None


# ---- creating nodes ---------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_a_node_created_without_flags_gets_them_all_off_and_needs_no_permission(
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
    assert [getattr(node, name) for name in _flags(kind.prefix, (0, 0, 0))] == [False] * 3


@pytest.mark.django_db
def test_creating_a_python_node_over_the_viewset_defaults_the_flags_off(flow, no_files_client):
    response = no_files_client.post(
        "/api/pythonnodes/", {"graph": flow.pk, "python_code": CODE}, format="json"
    )

    assert response.status_code == status.HTTP_201_CREATED, response.content
    assert [response.data[name] for name in _flags("", (0, 0, 0))] == [False] * 3


@pytest.mark.django_db
def test_creating_a_node_with_explicit_all_off_flags_needs_no_permission(flow, no_files_client):
    body = {"graph": flow.pk, "python_code": CODE, **_flags("", (False, False, False))}

    response = no_files_client.post("/api/pythonnodes/", body, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_the_name_and_output_path_of_a_granted_node_are_not_locked(kind, flow, no_files_client):
    node = kind.make(flow, _granted(kind))
    body = {"output_variable_path": "variables.result"}
    if kind.model is not ClassificationDecisionTableNode:
        body["node_name"] = "renamed"

    response = _patch(no_files_client, kind, node, body)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_creating_a_node_with_a_flag_on_needs_the_permission(flow, no_files_client, read_client):
    body = {"graph": flow.pk, "python_code": CODE, "storage_grant_read": True}

    refused = no_files_client.post("/api/pythonnodes/", body, format="json")
    allowed = read_client.post("/api/pythonnodes/", body, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert allowed.status_code == status.HTTP_201_CREATED, allowed.content
    assert PythonNode.objects.filter(graph=flow).count() == 1


# ---- org scoping ------------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_another_orgs_node_is_a_404_not_a_403(kind, flow, beta, client_as, custom_role_user):
    node = kind.make(flow, _granted(kind))
    outsider = client_as(custom_role_user(beta, "outsider@example.com", {ResourceType.FLOWS: FLOWS_ALL}))
    outsider.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = _patch(outsider, kind, node, kind.steer)

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_moving_a_granted_node_to_another_flow_needs_its_grant(
    kind, acme, flow, no_files_client, admin_client
):
    other_flow = Graph.objects.create(name="other-flow", org=acme)
    node = kind.make(flow, _granted(kind))

    refused = _patch(no_files_client, kind, node, {"graph": other_flow.pk})
    stays = _patch(no_files_client, kind, node, {"graph": flow.pk})
    allowed = _patch(admin_client, kind, node, {"graph": other_flow.pk})

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["message"].startswith("This code runs with Files: Read,")
    assert stays.status_code == status.HTTP_200_OK
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert type(node).objects.get(pk=node.pk).graph_id == other_flow.pk


@pytest.mark.django_db
def test_moving_a_node_without_a_grant_is_free(acme, flow, no_files_client):
    other_flow = Graph.objects.create(name="other-flow-free", org=acme)
    node = PythonNode.objects.create(graph=flow, python_code=_code())

    response = _patch(no_files_client, KINDS[0], node, {"graph": other_flow.pk})

    assert response.status_code == status.HTTP_200_OK
