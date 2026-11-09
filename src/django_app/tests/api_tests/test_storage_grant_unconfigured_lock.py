"""The edit lock of a node whose storage grant is not configured.

A node migrated from before grants has no flags, and a trigger-started run of it gets read,
write and delete. So whoever changes what it does must hold those permissions, but only
where storage is involved: a legacy node that never touches files stays editable by anyone
who may edit the flow.
"""

import itertools

from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    AgentInlineSurface,
    AgentInlineSurfacePythonTool,
    InlineSurface,
    InlineSurfacePythonTool,
    Surface,
    SurfacePythonTool,
    ToolMode,
)
from proxies.sandbox.models import SandboxVenvBinding
from rbac.models.enums import Permission, ResourceType
from tables.graph_versioning.services import GraphVersioningService
from tables.models import AgentNodeTask, Graph, PythonCode, PythonCodeTool
from tables.models.graph_models import (
    AgentNode,
    AudioTranscriptionNode,
    ClassificationDecisionTableNode,
    FileExtractorNode,
    PythonNode,
    StartNode,
    TaskNode,
    WebhookTriggerNode,
)
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ALL = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
FLOWS_ALL = ALL | Permission.USE
FILES_WITHOUT_DELETE = Permission.READ | Permission.CREATE | Permission.UPDATE
CODE = {"code": "def main(): return 1", "entrypoint": "main"}
EDITED_CODE = {"code": "def main(): return 2", "entrypoint": "main"}
MISSING_DELETE = (
    "This code runs with Files: Delete, which you don't have. Contact an admin to change it."
)
EVERYTHING = ["read", "write", "delete"]


def _code():
    return PythonCode.objects.create(**CODE)


_tool_names = itertools.count()


def _tool(acme, *, use_storage, name=None):
    return PythonCodeTool.objects.create(
        org=acme,
        name=name or f"tool-{next(_tool_names)}",
        description="d",
        variables=[],
        python_code=PythonCode.objects.create(**CODE),
        built_in=False,
        use_storage=use_storage,
    )


def _surface_with(acme, tool, name=None):
    surface = Surface.objects.create(
        org=acme, name=name or f"surface-{next(_tool_names)}", owner_agent=None
    )
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
    return surface


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="legacy-flow", org=acme)


def _client(client_as, custom_role_user, acme, email, files):
    permissions = {
        ResourceType.FLOWS: FLOWS_ALL,
        ResourceType.TOOLS: ALL,
        ResourceType.SURFACES: ALL,
        ResourceType.AGENTS: ALL,
        ResourceType.VENVS: ALL,
        ResourceType.WEBHOOKS: FLOWS_ALL,
        ResourceType.AUDIT: Permission.READ,
    }
    if files:
        permissions[ResourceType.FILES] = files
    client = client_as(custom_role_user(acme, email, permissions))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def member(client_as, custom_role_user, acme):
    """Edits flows and tools, and may read, create and update files, but not delete them."""
    return _client(client_as, custom_role_user, acme, "member@example.com", FILES_WITHOUT_DELETE)


@pytest.fixture
def no_files(client_as, custom_role_user, acme):
    return _client(client_as, custom_role_user, acme, "nofiles@example.com", None)


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _bulk(client, graph, list_key, item):
    graph.refresh_from_db()
    return client.post(
        reverse("graphs-save-flow", args=[graph.pk]),
        {"save_version": graph.save_version, list_key: [{**item, "graph": graph.pk}]},
        format="json",
    )


def _assert_refused(response, missing=("delete",)):
    assert response.status_code == status.HTTP_403_FORBIDDEN, response.content
    assert response.data["missing_grants"] == list(missing)


# ---- code slots with a storage switch ---------------------------------------


@pytest.mark.django_db
def test_editing_the_code_of_a_not_configured_python_node_that_uses_storage_is_locked(
    flow, member, admin_client
):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=True)
    body = {"python_code": EDITED_CODE}

    refused = member.patch(f"/api/pythonnodes/{node.pk}/", body, format="json")
    allowed = admin_client.patch(f"/api/pythonnodes/{node.pk}/", body, format="json")

    _assert_refused(refused)
    assert refused.data["message"] == MISSING_DELETE
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    node.python_code.refresh_from_db()
    assert node.python_code.code == EDITED_CODE["code"]


@pytest.mark.django_db
def test_a_refused_edit_of_a_not_configured_node_changes_nothing(flow, member):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=True)

    member.patch(f"/api/pythonnodes/{node.pk}/", {"python_code": EDITED_CODE}, format="json")

    node.python_code.refresh_from_db()
    assert node.python_code.code == CODE["code"]


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
def test_turning_storage_on_for_a_not_configured_python_node_is_locked(
    entry, flow, member, admin_client
):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=False)

    def attempt(client):
        if entry == "viewset":
            return client.patch(f"/api/pythonnodes/{node.pk}/", {"use_storage": True}, format="json")
        return _bulk(
            client,
            flow,
            "python_node_list",
            {"id": node.pk, "python_code": CODE, "use_storage": True},
        )

    refused = attempt(member)
    allowed = attempt(admin_client)

    _assert_refused(refused)
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert PythonNode.objects.get(pk=node.pk).use_storage is True


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
def test_editing_the_code_of_a_not_configured_python_node_without_storage_is_free(
    entry, flow, no_files
):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=False)

    if entry == "viewset":
        response = no_files.patch(
            f"/api/pythonnodes/{node.pk}/", {"python_code": EDITED_CODE}, format="json"
        )
    else:
        response = _bulk(
            no_files,
            flow,
            "python_node_list",
            {"id": node.pk, "python_code": EDITED_CODE, "use_storage": False},
        )

    assert response.status_code == status.HTTP_200_OK, response.content
    node.python_code.refresh_from_db()
    assert node.python_code.code == EDITED_CODE["code"]


@pytest.mark.django_db
def test_turning_storage_off_on_a_not_configured_node_is_locked_too(flow, member):
    node = PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=True)

    response = member.patch(f"/api/pythonnodes/{node.pk}/", {"use_storage": False}, format="json")

    _assert_refused(response)


@pytest.mark.django_db
def test_a_not_configured_webhook_node_that_uses_storage_is_locked_and_one_that_does_not_is_free(
    flow, member
):
    using = WebhookTriggerNode.objects.create(
        graph=flow, node_name="using", python_code=_code(), use_storage=True
    )
    not_using = WebhookTriggerNode.objects.create(
        graph=flow, node_name="not-using", python_code=_code(), use_storage=False
    )
    url = "/api/webhook-trigger-nodes/"
    body = {"python_code": EDITED_CODE}

    refused = member.patch(f"{url}{using.pk}/", body, format="json")
    free = member.patch(f"{url}{not_using.pk}/", body, format="json")

    _assert_refused(refused)
    assert free.status_code == status.HTTP_200_OK, free.content


@pytest.mark.django_db
def test_each_code_slot_of_a_not_configured_classification_table_is_locked_by_its_own_storage(
    flow, member
):
    node = ClassificationDecisionTableNode.objects.create(
        graph=flow, pre_python_code=_code(), post_python_code=_code(), pre_use_storage=True
    )
    url = f"/api/classification-decision-table-node/{node.pk}/"

    pre = member.patch(url, {"pre_input_map": {"a": "variables.b"}}, format="json")
    post = member.patch(url, {"post_input_map": {"a": "variables.b"}}, format="json")

    _assert_refused(pre)
    assert post.status_code == status.HTTP_200_OK, post.content


@pytest.mark.django_db
def test_turning_storage_on_in_a_classification_slot_that_is_not_configured_is_locked(
    flow, member
):
    node = ClassificationDecisionTableNode.objects.create(
        graph=flow, pre_python_code=_code(), post_python_code=_code()
    )

    response = member.patch(
        f"/api/classification-decision-table-node/{node.pk}/",
        {"post_use_storage": True},
        format="json",
    )

    _assert_refused(response)


# ---- nodes that always read storage -----------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
@pytest.mark.parametrize(
    ("model", "url", "list_key"),
    [
        (FileExtractorNode, "/api/file-extractor-nodes/", "file_extractor_node_list"),
        (AudioTranscriptionNode, "/api/audio-transcription-nodes/", "audio_transcription_node_list"),
    ],
    ids=["file_extractor", "audio"],
)
def test_a_not_configured_node_that_always_reads_storage_is_locked(
    model, url, list_key, entry, flow, member, admin_client
):
    node = model.objects.create(graph=flow)
    change = {"input_map": {"a": "variables.b"}}

    def attempt(client):
        if entry == "viewset":
            return client.patch(f"{url}{node.pk}/", change, format="json")
        return _bulk(client, flow, list_key, {"id": node.pk, **change})

    refused = attempt(member)
    allowed = attempt(admin_client)

    _assert_refused(refused)
    assert refused.data["missing_grants"] == ["delete"]
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert model.objects.get(pk=node.pk).input_map == change["input_map"]


@pytest.mark.django_db
def test_a_not_configured_node_that_always_reads_storage_names_every_missing_permission(
    flow, no_files
):
    node = FileExtractorNode.objects.create(graph=flow)

    response = no_files.patch(
        f"/api/file-extractor-nodes/{node.pk}/", {"input_map": {"a": "b"}}, format="json"
    )

    _assert_refused(response, EVERYTHING)
    assert response.data["message"].startswith(
        "This code runs with Files: Read, Files: Create, Files: Update, Files: Delete,"
    )


# ---- agent and task nodes: storage through tools ----------------------------


@pytest.mark.django_db
def test_the_prompt_of_a_not_configured_task_node_is_locked_only_when_it_has_a_storage_tool(
    acme, flow, member, admin_client
):
    with_storage = TaskNode.objects.create(graph=flow, instructions="summarize")
    with_storage.surface_list.add(_surface_with(acme, _tool(acme, use_storage=True)))
    without_storage = TaskNode.objects.create(graph=flow, instructions="summarize")
    without_storage.surface_list.add(
        _surface_with(acme, _tool(acme, use_storage=False, name="plain"), "plain-surface")
    )
    bare = TaskNode.objects.create(graph=flow, instructions="summarize")
    body = {"instructions": "wipe the folder"}

    refused = member.patch(f"/api/tasknodes/{with_storage.pk}/", body, format="json")
    allowed = admin_client.patch(f"/api/tasknodes/{with_storage.pk}/", body, format="json")
    free_plain = member.patch(f"/api/tasknodes/{without_storage.pk}/", body, format="json")
    free_bare = member.patch(f"/api/tasknodes/{bare.pk}/", body, format="json")

    _assert_refused(refused)
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert free_plain.status_code == status.HTTP_200_OK, free_plain.content
    assert free_bare.status_code == status.HTTP_200_OK, free_bare.content


def _storage_tool_through(route, acme, flow, node_model=AgentNode):
    """A not-configured node using a tool with storage on, reached the way `route` says."""
    tool = _tool(acme, use_storage=True)
    if route == "inline":
        node = node_model.objects.create(graph=flow)
        if node_model is AgentNode:
            inline = AgentInlineSurface.objects.create(agent_node=node)
            AgentInlineSurfacePythonTool.objects.create(
                agent_inline_surface=inline, python_tool=tool, mode=ToolMode.ALLOW
            )
        else:
            inline = InlineSurface.objects.create(task_node=node)
            InlineSurfacePythonTool.objects.create(
                inline_surface=inline, python_tool=tool, mode=ToolMode.ALLOW
            )
    elif route == "agent_default":
        agent = AgentDefinition.objects.create(
            org=acme, name="agent", instruction_list=[{"name": "i.md", "content": "x"}]
        )
        AgentDefaultSurface.objects.create(
            agent_definition=agent, surface=_surface_with(acme, tool), place="all"
        )
        node = node_model.objects.create(graph=flow, agent_definition=agent)
    else:
        node = node_model.objects.create(graph=flow)
        node.surface_list.add(_surface_with(acme, tool))
    return node, tool


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["surface", "inline", "agent_default"])
@pytest.mark.parametrize("node_model", [AgentNode, TaskNode], ids=["agent", "task"])
def test_a_storage_tool_makes_a_not_configured_node_locked_however_it_reaches_the_node(
    route, node_model, acme, flow, member
):
    node, _ = _storage_tool_through(route, acme, flow, node_model)
    url = "/api/agentnodes/" if node_model is AgentNode else "/api/tasknodes/"

    response = member.patch(f"{url}{node.pk}/", {"input_map": {"a": "variables.b"}}, format="json")

    _assert_refused(response)


@pytest.mark.django_db
def test_the_tasks_of_a_not_configured_agent_node_are_locked_only_with_a_storage_tool(
    acme, flow, member
):
    node, _ = _storage_tool_through("surface", acme, flow)
    task = AgentNodeTask.objects.create(agent_node=node, name="t", order=0, instructions="a")
    bare = AgentNode.objects.create(graph=flow)
    bare_task = AgentNodeTask.objects.create(agent_node=bare, name="t", order=0, instructions="a")

    refused_update = member.patch(
        f"/api/agentnodetasks/{task.pk}/", {"instructions": "wipe it"}, format="json"
    )
    refused_create = member.post(
        "/api/agentnodetasks/",
        {"agent_node": node.pk, "name": "new", "order": 1, "instructions": "b"},
        format="json",
    )
    refused_nested = member.patch(
        f"/api/agentnodes/{node.pk}/",
        {"tasks": [{"id": task.pk, "name": "t", "order": 0, "instructions": "changed"}]},
        format="json",
    )
    free = member.patch(
        f"/api/agentnodetasks/{bare_task.pk}/", {"instructions": "wipe it"}, format="json"
    )

    _assert_refused(refused_update)
    _assert_refused(refused_create)
    _assert_refused(refused_nested)
    assert free.status_code == status.HTTP_200_OK, free.content


@pytest.mark.django_db
@pytest.mark.parametrize("entry", ["viewset", "bulk_save"])
def test_attaching_a_storage_tool_to_a_not_configured_node_is_locked(
    entry, acme, flow, member, admin_client
):
    node = AgentNode.objects.create(graph=flow)
    surface = _surface_with(acme, _tool(acme, use_storage=True))

    def attempt(client):
        if entry == "viewset":
            return client.patch(
                f"/api/agentnodes/{node.pk}/", {"surface_list": [surface.pk]}, format="json"
            )
        return _bulk(client, flow, "agent_node_list", {"id": node.pk, "surface_list": [surface.pk]})

    refused = attempt(member)
    allowed = attempt(admin_client)

    _assert_refused(refused)
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert list(node.surface_list.all()) == [surface]


@pytest.mark.django_db
def test_attaching_a_surface_without_a_storage_tool_to_a_not_configured_node_is_free(
    acme, flow, member
):
    node = AgentNode.objects.create(graph=flow)
    surface = _surface_with(acme, _tool(acme, use_storage=False))

    response = member.patch(
        f"/api/agentnodes/{node.pk}/", {"surface_list": [surface.pk]}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_a_not_configured_node_with_storage_tool_in_a_bulk_save_is_locked_and_without_is_free(
    acme, flow, member
):
    locked, _ = _storage_tool_through("surface", acme, flow)
    free = AgentNode.objects.create(graph=flow)
    change = {"input_map": {"a": "variables.b"}}

    refused = _bulk(member, flow, "agent_node_list", {"id": locked.pk, **change})
    allowed = _bulk(member, flow, "agent_node_list", {"id": free.pk, **change})

    _assert_refused(refused)
    assert allowed.status_code == status.HTTP_200_OK, allowed.content


# ---- what the node reaches: tools, surfaces, agents, venvs ------------------


@pytest.mark.django_db
def test_editing_a_storage_tool_a_not_configured_node_uses_needs_the_full_grant(
    acme, flow, member, admin_client
):
    _, tool = _storage_tool_through("surface", acme, flow)
    url = f"/api/python-code-tool/{tool.pk}/"
    body = {"python_code": EDITED_CODE}

    refused = member.patch(url, body, format="json")
    allowed = admin_client.patch(url, body, format="json")

    _assert_refused(refused)
    assert allowed.status_code == status.HTTP_200_OK, allowed.content


@pytest.mark.django_db
def test_editing_a_plain_tool_is_locked_when_the_not_configured_node_also_uses_a_storage_tool(
    acme, flow, member
):
    node, _ = _storage_tool_through("surface", acme, flow)
    plain = _tool(acme, use_storage=False, name="plain")
    node.surface_list.add(_surface_with(acme, plain, "plain-surface"))

    response = member.patch(
        f"/api/python-code-tool/{plain.pk}/", {"python_code": EDITED_CODE}, format="json"
    )

    _assert_refused(response)


@pytest.mark.django_db
def test_editing_a_tool_only_not_configured_nodes_without_storage_use_is_free(
    acme, flow, member
):
    plain = _tool(acme, use_storage=False)
    AgentNode.objects.create(graph=flow).surface_list.add(_surface_with(acme, plain))

    response = member.patch(
        f"/api/python-code-tool/{plain.pk}/", {"python_code": EDITED_CODE}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_switching_storage_on_for_a_tool_a_not_configured_node_uses_is_locked(
    acme, flow, member, admin_client
):
    plain = _tool(acme, use_storage=False)
    AgentNode.objects.create(graph=flow).surface_list.add(_surface_with(acme, plain))
    url = f"/api/python-code-tool/{plain.pk}/"

    refused = member.patch(url, {"use_storage": True}, format="json")
    allowed = admin_client.patch(url, {"use_storage": True}, format="json")

    _assert_refused(refused)
    assert allowed.status_code == status.HTTP_200_OK, allowed.content


@pytest.mark.django_db
def test_the_tool_api_shows_the_lock_a_not_configured_node_puts_on_a_storage_tool(
    acme, flow, member
):
    _, tool = _storage_tool_through("surface", acme, flow)
    plain = _tool(acme, use_storage=False, name="plain")
    AgentNode.objects.create(graph=flow).surface_list.add(_surface_with(acme, plain, "p"))

    locked = member.get(f"/api/python-code-tool/{tool.pk}/")
    unlocked = member.get(f"/api/python-code-tool/{plain.pk}/")

    assert locked.data["storage_grant_lock"]["required_grants"] == EVERYTHING
    assert locked.data["storage_grant_lock"]["required_permissions"] == [
        "Files: Read",
        "Files: Create",
        "Files: Update",
        "Files: Delete",
    ]
    assert unlocked.data["storage_grant_lock"] is None


@pytest.mark.django_db
def test_changing_a_surface_a_not_configured_node_attaches_is_locked_when_storage_is_involved(
    acme, flow, member
):
    storage_tool = _tool(acme, use_storage=True)
    plain_tool = _tool(acme, use_storage=False, name="plain")
    in_use = _surface_with(acme, storage_tool, "in-use")
    AgentNode.objects.create(graph=flow).surface_list.add(in_use)
    quiet = Surface.objects.create(org=acme, name="quiet", owner_agent=None)
    AgentNode.objects.create(graph=flow).surface_list.add(quiet)

    edit_in_use = member.patch(
        f"/api/surfaces/{in_use.pk}/", {"instructions": "run everything"}, format="json"
    )
    add_storage_tool = member.patch(
        f"/api/surfaces/{quiet.pk}/",
        {"python_tools": [{"python_tool": storage_tool.pk, "mode": "allow"}]},
        format="json",
    )
    add_plain_tool = member.patch(
        f"/api/surfaces/{quiet.pk}/",
        {"python_tools": [{"python_tool": plain_tool.pk, "mode": "allow"}]},
        format="json",
    )

    _assert_refused(edit_in_use)
    _assert_refused(add_storage_tool)
    assert add_plain_tool.status_code == status.HTTP_200_OK, add_plain_tool.content


@pytest.mark.django_db
def test_changing_an_agent_a_not_configured_node_runs_is_locked_when_it_has_a_storage_tool(
    acme, flow, member
):
    _, tool = _storage_tool_through("agent_default", acme, flow)
    agent = AgentDefinition.objects.get(org=acme, name="agent")
    quiet_agent = AgentDefinition.objects.create(
        org=acme, name="quiet", instruction_list=[{"name": "i.md", "content": "x"}]
    )
    AgentNode.objects.create(graph=flow, agent_definition=quiet_agent)
    storage_surface = _surface_with(acme, tool, "other-storage-surface")

    instructions = member.patch(
        f"/api/agent-definitions/{agent.pk}/",
        {"instruction_list": [{"name": "i.md", "content": "wipe"}]},
        format="json",
    )
    gains_storage = member.patch(
        f"/api/agent-definitions/{quiet_agent.pk}/",
        {"default_surfaces": [{"surface": storage_surface.pk, "place": "all"}]},
        format="json",
    )
    quiet_edit = member.patch(
        f"/api/agent-definitions/{quiet_agent.pk}/",
        {"instruction_list": [{"name": "i.md", "content": "fine"}]},
        format="json",
    )

    _assert_refused(instructions)
    _assert_refused(gains_storage)
    assert quiet_edit.status_code == status.HTTP_200_OK, quiet_edit.content


# ---- the configured slots keep their rule -----------------------------------


@pytest.mark.django_db
def test_a_configured_slot_is_still_locked_by_its_flags_only(flow, member):
    granting_read = PythonNode.objects.create(
        graph=flow,
        python_code=_code(),
        use_storage=True,
        storage_grant_read=True,
        storage_grant_write=False,
        storage_grant_delete=False,
    )
    granting_nothing = PythonNode.objects.create(
        graph=flow,
        python_code=_code(),
        use_storage=True,
        storage_grant_read=False,
        storage_grant_write=False,
        storage_grant_delete=False,
    )

    allowed_by_read = member.patch(
        f"/api/pythonnodes/{granting_read.pk}/", {"python_code": EDITED_CODE}, format="json"
    )
    nothing_granted = member.patch(
        f"/api/pythonnodes/{granting_nothing.pk}/", {"python_code": EDITED_CODE}, format="json"
    )

    assert allowed_by_read.status_code == status.HTTP_200_OK, allowed_by_read.content
    assert nothing_granted.status_code == status.HTTP_200_OK, nothing_granted.content


# ---- bulk save query counts -------------------------------------------------


@pytest.mark.django_db
def test_checking_not_configured_agent_nodes_that_use_a_storage_tool_costs_no_query_per_node(
    acme, admin_client
):
    checked_for_nothing = {
        "storage_grant_read": False,
        "storage_grant_write": False,
        "storage_grant_delete": False,
    }

    def saved_queries(flow_name, node_count, flags):
        flow = Graph.objects.create(name=flow_name, org=acme)
        nodes = []
        for _ in range(node_count):
            node, _ = _storage_tool_through("surface", acme, flow)
            AgentNode.objects.filter(pk=node.pk).update(**flags)
            nodes.append(node)
        items = [
            {"id": node.pk, "graph": flow.pk, "input_map": {"v": f"variables.{node.pk}"}}
            for node in nodes
        ]
        with CaptureQueriesContext(connection) as captured:
            response = admin_client.post(
                reverse("graphs-save-flow", args=[flow.pk]),
                {"save_version": flow.save_version, "agent_node_list": items},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.content
        return len(captured.captured_queries)

    # The save itself costs queries per node; what the check adds on top must not grow.
    def added_by_the_check(node_count):
        return saved_queries(f"legacy-tool-{node_count}", node_count, {}) - saved_queries(
            f"nothing-tool-{node_count}", node_count, checked_for_nothing
        )

    assert added_by_the_check(2) == added_by_the_check(6)


@pytest.mark.django_db
def test_the_bulk_save_check_of_changed_surfaces_costs_no_query_per_node(acme, admin_client):
    plain_surface = _surface_with(acme, _tool(acme, use_storage=False))
    checked_for_nothing = {
        "storage_grant_read": False,
        "storage_grant_write": False,
        "storage_grant_delete": False,
    }

    def saved_queries(flow_name, node_count, flags):
        flow = Graph.objects.create(name=flow_name, org=acme)
        nodes = [AgentNode.objects.create(graph=flow, **flags) for _ in range(node_count)]
        items = [
            {"id": node.pk, "graph": flow.pk, "surface_list": [plain_surface.pk]} for node in nodes
        ]
        with CaptureQueriesContext(connection) as captured:
            response = admin_client.post(
                reverse("graphs-save-flow", args=[flow.pk]),
                {"save_version": flow.save_version, "agent_node_list": items},
                format="json",
            )
        assert response.status_code == status.HTTP_200_OK, response.content
        return len(captured.captured_queries)

    # The save itself costs queries per node; what the check adds on top must not grow.
    def added_by_the_check(node_count):
        return saved_queries(f"legacy-{node_count}", node_count, {}) - saved_queries(
            f"nothing-{node_count}", node_count, checked_for_nothing
        )

    assert added_by_the_check(2) == added_by_the_check(6)


# ---- what does not count, and what stays locked -----------------------------


@pytest.mark.django_db
def test_a_storage_tool_that_is_only_denied_does_not_make_a_not_configured_node_locked(
    acme, flow, member
):
    surface = Surface.objects.create(org=acme, name="deny-surface", owner_agent=None)
    SurfacePythonTool.objects.create(
        surface=surface, python_tool=_tool(acme, use_storage=True), mode=ToolMode.DENY
    )
    node = AgentNode.objects.create(graph=flow)
    node.surface_list.add(surface)

    response = member.patch(
        f"/api/agentnodes/{node.pk}/", {"input_map": {"a": "variables.b"}}, format="json"
    )

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_removing_the_storage_tool_and_steering_in_the_same_write_stays_locked(acme, flow, member):
    node, _ = _storage_tool_through("surface", acme, flow)

    response = member.patch(
        f"/api/agentnodes/{node.pk}/",
        {"surface_list": [], "input_map": {"a": "variables.b"}},
        format="json",
    )

    _assert_refused(response)
    assert node.surface_list.count() == 1


@pytest.mark.django_db
def test_switching_storage_off_while_editing_the_code_of_a_tool_stays_locked(acme, flow, member):
    _, tool = _storage_tool_through("surface", acme, flow)

    response = member.patch(
        f"/api/python-code-tool/{tool.pk}/",
        {"use_storage": False, "python_code": EDITED_CODE},
        format="json",
    )

    _assert_refused(response)
    tool.refresh_from_db()
    assert tool.use_storage is True


@pytest.mark.django_db
def test_moving_a_not_configured_node_that_touches_storage_to_another_flow_is_locked(
    acme, flow, member
):
    other_flow = Graph.objects.create(name="other-flow", org=acme)
    reading = FileExtractorNode.objects.create(graph=flow)
    quiet = PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=False)

    refused = member.patch(
        f"/api/file-extractor-nodes/{reading.pk}/", {"graph": other_flow.pk}, format="json"
    )
    free = member.patch(f"/api/pythonnodes/{quiet.pk}/", {"graph": other_flow.pk}, format="json")

    _assert_refused(refused)
    assert free.status_code == status.HTTP_200_OK, free.content


# ---- virtualenvs ------------------------------------------------------------


@pytest.fixture
def venv(acme):
    return SandboxVenvBinding.objects.create(org_id=acme.id, resource_id="9002")


@pytest.mark.django_db
@pytest.mark.parametrize(("use_storage", "expected"), [(True, 403), (False, 200)])
def test_changing_a_venv_is_locked_by_not_configured_code_only_when_that_code_uses_storage(
    use_storage, expected, flow, venv, member
):
    PythonNode.objects.create(
        graph=flow,
        python_code=PythonCode.objects.create(code="x", venv=venv),
        use_storage=use_storage,
    )

    with patch("proxies.sandbox.services.VenvService.update", return_value={"libs": ["x"]}):
        response = member.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert response.status_code == expected, response.content


@pytest.mark.django_db
def test_changing_a_venv_a_not_configured_storage_tool_runs_in_is_locked(acme, flow, venv, member):
    tool = _tool(acme, use_storage=True)
    tool.python_code.venv = venv
    tool.python_code.save()
    AgentNode.objects.create(graph=flow).surface_list.add(_surface_with(acme, tool))

    with patch("proxies.sandbox.services.VenvService.update", return_value={"libs": ["x"]}):
        response = member.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    _assert_refused(response)


# ---- restoring a version ----------------------------------------------------


def _restore(client, flow):
    version = GraphVersioningService().save_version(graph=flow, name="legacy")
    return _restore_version(client, flow, version)


def _restore_version(client, flow, version):
    flow.refresh_from_db()
    return client.post(
        reverse("graph-versions-restore", args=[version.id]),
        {"save_version": flow.save_version},
        format="json",
    )


@pytest.mark.django_db
def test_restoring_over_a_not_configured_agent_node_with_a_storage_tool_needs_every_grant(
    acme, flow, member, admin_client
):
    StartNode.objects.create(graph=flow, variables={})
    _storage_tool_through("surface", acme, flow)

    refused = _restore(member, flow)
    allowed = _restore(admin_client, flow)

    _assert_refused(refused)
    assert allowed.status_code == status.HTTP_200_OK, allowed.content


@pytest.mark.django_db
def test_restoring_over_a_not_configured_agent_node_without_a_storage_tool_is_free(
    acme, flow, member
):
    StartNode.objects.create(graph=flow, variables={})
    AgentNode.objects.create(graph=flow).surface_list.add(
        _surface_with(acme, _tool(acme, use_storage=False))
    )

    response = _restore(member, flow)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_restoring_over_a_not_configured_file_extractor_needs_every_grant(flow, member):
    StartNode.objects.create(graph=flow, variables={})
    FileExtractorNode.objects.create(graph=flow)

    _assert_refused(_restore(member, flow))


@pytest.mark.django_db
def test_restoring_not_configured_python_nodes_that_do_not_use_storage_is_free(flow, member):
    StartNode.objects.create(graph=flow, variables={})
    PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=False)

    response = _restore(member, flow)

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_restoring_a_version_whose_not_configured_node_uses_storage_needs_every_grant(
    flow, member
):
    StartNode.objects.create(graph=flow, variables={})
    node = PythonNode.objects.create(graph=flow, python_code=_code(), use_storage=True)
    version = GraphVersioningService().save_version(graph=flow, name="with-storage")
    PythonNode.objects.filter(pk=node.pk).update(use_storage=False)

    _assert_refused(_restore_version(member, flow, version))
