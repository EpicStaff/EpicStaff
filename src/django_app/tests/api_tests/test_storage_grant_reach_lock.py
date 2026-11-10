"""What steers a granted node's code is locked wherever it can be edited, not only on the node.

A granted agent or task node runs the tools of its surfaces as its prompt says; code in a
virtualenv runs with the libraries installed there. So a surface, an agent definition, an
agent node's tasks and a venv are locked by the grants of the nodes that reach them.
"""

from unittest.mock import patch

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework import status

from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfacePythonTool,
    ToolMode,
)
from proxies.sandbox.models import SandboxVenvBinding
from rbac.models.enums import Permission, ResourceType
from tables.models import AgentNodeTask, Graph, PythonCode, PythonCodeTool
from tables.models.graph_models import AgentNode, PythonNode, TaskNode
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ALL = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
RW_GRANT = {"storage_grant_read": True, "storage_grant_write": True, "storage_grant_delete": False}
READ_AND_WRITE = (
    "This code runs with Files: Read, Files: Create, Files: Update, which you don't have. "
    "Contact an admin to change it."
)


def _tool(acme, name="reach-tool", venv=None):
    return PythonCodeTool.objects.create(
        org=acme,
        name=name,
        description="d",
        variables=[],
        python_code=PythonCode.objects.create(code="def main(): return 1", venv=venv),
        built_in=False,
    )


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="reach-flow", org=acme)


@pytest.fixture
def surface(acme):
    return Surface.objects.create(org=acme, name="reach-surface", owner_agent=None)


@pytest.fixture
def agent(acme):
    return AgentDefinition.objects.create(
        org=acme, name="reach-agent", instruction_list=[{"name": "i.md", "content": "x"}]
    )


@pytest.fixture
def editor(client_as, custom_role_user, acme):
    """Edits everything except files: no FILES permission at all."""
    permissions = {
        ResourceType.FLOWS: ALL,
        ResourceType.TOOLS: ALL,
        ResourceType.SURFACES: ALL,
        ResourceType.AGENTS: ALL,
        ResourceType.VENVS: ALL,
    }
    client = client_as(custom_role_user(acme, "reach-editor@example.com", permissions))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


# ---- surfaces ---------------------------------------------------------------


@pytest.mark.django_db
def test_changing_the_tools_of_a_surface_a_granted_node_attaches_needs_that_nodes_grant(
    acme, flow, surface, editor, admin_client
):
    tool = _tool(acme)
    AgentNode.objects.create(graph=flow, **RW_GRANT).surface_list.add(surface)
    body = {"python_tools": [{"python_tool": tool.pk, "mode": "allow"}]}

    refused = editor.patch(f"/api/surfaces/{surface.pk}/", body, format="json")
    allowed = admin_client.patch(f"/api/surfaces/{surface.pk}/", body, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == READ_AND_WRITE
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert SurfacePythonTool.objects.filter(surface=surface).count() == 1


@pytest.mark.django_db
def test_a_surface_the_agent_of_a_granted_node_defaults_to_is_locked_too(
    acme, flow, surface, agent, editor
):
    AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface, place="all")
    TaskNode.objects.create(graph=flow, agent_definition=agent, **RW_GRANT)

    response = editor.patch(
        f"/api/surfaces/{surface.pk}/", {"instructions": "run everything"}, format="json"
    )

    assert response.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
def test_renaming_a_surface_or_resending_its_tools_is_free_and_so_is_an_unreached_surface(
    acme, flow, surface, editor
):
    tool = _tool(acme)
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
    AgentNode.objects.create(graph=flow, **RW_GRANT).surface_list.add(surface)
    unreached = Surface.objects.create(org=acme, name="unreached", owner_agent=None)

    rename = editor.patch(f"/api/surfaces/{surface.pk}/", {"name": "renamed"}, format="json")
    resend = editor.patch(
        f"/api/surfaces/{surface.pk}/",
        {"python_tools": [{"python_tool": tool.pk, "mode": "allow"}]},
        format="json",
    )
    elsewhere = editor.patch(
        f"/api/surfaces/{unreached.pk}/", {"instructions": "anything"}, format="json"
    )

    assert [rename.status_code, resend.status_code, elsewhere.status_code] == [200, 200, 200]


@pytest.mark.django_db
def test_another_orgs_surface_is_a_404_not_a_403(acme, beta, flow, surface, client_as, custom_role_user):
    AgentNode.objects.create(graph=flow, **RW_GRANT).surface_list.add(surface)
    outsider = client_as(
        custom_role_user(beta, "reach-outsider@example.com", {ResourceType.SURFACES: ALL})
    )
    outsider.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = outsider.patch(f"/api/surfaces/{surface.pk}/", {"instructions": "x"}, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


# ---- agent definitions ------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("node_model", [AgentNode, TaskNode])
def test_the_instructions_of_an_agent_a_granted_node_runs_are_locked(
    node_model, acme, flow, agent, editor, admin_client
):
    node_model.objects.create(graph=flow, agent_definition=agent, **RW_GRANT)
    body = {"instruction_list": [{"name": "i.md", "content": "delete everything"}]}

    refused = editor.patch(f"/api/agent-definitions/{agent.pk}/", body, format="json")
    allowed = admin_client.patch(f"/api/agent-definitions/{agent.pk}/", body, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == READ_AND_WRITE
    assert allowed.status_code == status.HTTP_200_OK, allowed.content


@pytest.mark.django_db
def test_default_surfaces_of_such_an_agent_are_locked_but_a_rename_and_a_resend_are_not(
    acme, flow, agent, surface, editor
):
    TaskNode.objects.create(graph=flow, agent_definition=agent, **RW_GRANT)

    added = editor.patch(
        f"/api/agent-definitions/{agent.pk}/",
        {"default_surfaces": [{"surface": surface.pk, "place": "all"}]},
        format="json",
    )
    rename = editor.patch(f"/api/agent-definitions/{agent.pk}/", {"name": "renamed"}, format="json")
    resend = editor.patch(
        f"/api/agent-definitions/{agent.pk}/",
        {"instruction_list": [{"name": "i.md", "content": "x"}]},
        format="json",
    )

    assert added.status_code == status.HTTP_403_FORBIDDEN
    assert rename.status_code == status.HTTP_200_OK
    assert resend.status_code == status.HTTP_200_OK


# ---- agent node tasks and task node prompts ---------------------------------


@pytest.fixture
def task_of_granted_node(flow):
    node = AgentNode.objects.create(graph=flow, **RW_GRANT)
    return AgentNodeTask.objects.create(agent_node=node, name="t", order=0, instructions="a")


@pytest.mark.django_db
def test_writing_a_task_of_a_granted_agent_node_needs_the_nodes_grant(
    task_of_granted_node, editor, admin_client
):
    node = task_of_granted_node.agent_node
    url = f"/api/agentnodetasks/{task_of_granted_node.pk}/"

    created = editor.post(
        "/api/agentnodetasks/",
        {"agent_node": node.pk, "name": "new", "order": 1, "instructions": "b"},
        format="json",
    )
    updated = editor.patch(url, {"instructions": "delete all files"}, format="json")
    deleted = editor.delete(url)
    allowed = admin_client.patch(url, {"instructions": "fine"}, format="json")

    assert [created.status_code, updated.status_code, deleted.status_code] == [403, 403, 403]
    assert created.data["message"] == READ_AND_WRITE
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert AgentNodeTask.objects.filter(agent_node=node).count() == 1


@pytest.mark.django_db
def test_tasks_of_an_agent_node_without_a_grant_are_free(flow, editor):
    node = AgentNode.objects.create(graph=flow)
    task = AgentNodeTask.objects.create(agent_node=node, name="t", order=0)

    response = editor.patch(f"/api/agentnodetasks/{task.pk}/", {"instructions": "x"}, format="json")

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_the_tasks_sent_with_an_agent_node_are_locked_when_they_change_not_when_resent(
    task_of_granted_node, editor
):
    node = task_of_granted_node.agent_node
    same = [{"id": task_of_granted_node.pk, "name": "t", "order": 0, "instructions": "a"}]
    changed = [{"id": task_of_granted_node.pk, "name": "t", "order": 0, "instructions": "b"}]

    resend = editor.patch(f"/api/agentnodes/{node.pk}/", {"tasks": same}, format="json")
    edit = editor.patch(f"/api/agentnodes/{node.pk}/", {"tasks": changed}, format="json")

    assert resend.status_code == status.HTTP_200_OK, resend.content
    assert edit.status_code == status.HTTP_403_FORBIDDEN


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change", [{"instructions": "wipe the folder"}, {"output_schema": {"type": "object"}}]
)
def test_the_prompt_of_a_granted_task_node_is_locked(change, flow, editor):
    node = TaskNode.objects.create(graph=flow, instructions="summarize", **RW_GRANT)

    refused = editor.patch(f"/api/tasknodes/{node.pk}/", change, format="json")
    resend = editor.patch(f"/api/tasknodes/{node.pk}/", {"instructions": "summarize"}, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert resend.status_code == status.HTTP_200_OK


# ---- virtualenvs ------------------------------------------------------------


@pytest.fixture
def venv(acme):
    return SandboxVenvBinding.objects.create(org_id=acme.id, resource_id="9001")


@pytest.fixture
def upstream():
    with patch("proxies.sandbox.services.VenvService.update", return_value={"libs": ["x"]}) as update:
        yield update


@pytest.mark.django_db
def test_changing_a_venv_that_granted_code_runs_in_needs_that_codes_grant(
    flow, venv, editor, admin_client, upstream
):
    PythonNode.objects.create(
        graph=flow, python_code=PythonCode.objects.create(code="x", venv=venv), **RW_GRANT
    )

    refused = editor.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")
    allowed = admin_client.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert refused.data["message"] == READ_AND_WRITE
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert upstream.call_count == 1


@pytest.mark.django_db
def test_a_venv_used_by_a_tool_of_a_granted_node_is_locked_too(
    acme, flow, venv, editor, upstream
):
    tool = _tool(acme, venv=venv)
    surface = Surface.objects.create(org=acme, name="venv-surface", owner_agent=None)
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
    TaskNode.objects.create(graph=flow, **RW_GRANT).surface_list.add(surface)

    response = editor.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    upstream.assert_not_called()


@pytest.mark.django_db
def test_a_venv_only_ungranted_code_uses_is_free(flow, venv, editor, upstream):
    PythonNode.objects.create(graph=flow, python_code=PythonCode.objects.create(code="x", venv=venv))

    response = editor.patch(f"/api/venvs/{venv.pk}/", {"libs": ["requests"]}, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content


# ---- the tool lock shows flow names only to those who may read flows --------


@pytest.mark.django_db
def test_flow_names_of_a_tool_lock_are_shown_only_to_a_caller_who_can_read_flows(
    acme, flow, client_as, custom_role_user, admin_client
):
    tool = _tool(acme)
    node = TaskNode.objects.create(graph=flow, **RW_GRANT)
    from agents.models import InlineSurface, InlineSurfacePythonTool

    InlineSurfacePythonTool.objects.create(
        inline_surface=InlineSurface.objects.create(task_node=node),
        python_tool=tool,
        mode=ToolMode.ALLOW,
    )
    tools_only = client_as(custom_role_user(acme, "tools-only@example.com", {ResourceType.TOOLS: ALL}))
    tools_only.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))

    hidden = tools_only.get(f"/api/python-code-tool/{tool.pk}/")
    shown = admin_client.get(f"/api/python-code-tool/{tool.pk}/")

    assert hidden.data["storage_grant_lock"]["flow_names"] == []
    assert hidden.data["storage_grant_lock"]["required_grants"] == ["read", "write"]
    assert shown.data["storage_grant_lock"]["flow_names"] == ["reach-flow"]


# ---- bulk save does not query per node --------------------------------------


@pytest.mark.django_db
def test_checking_granted_agent_nodes_in_a_bulk_save_costs_no_query_per_node(
    acme, admin_client
):
    def saved_queries(flow_name, grant):
        flow = Graph.objects.create(name=flow_name, org=acme)
        nodes = [AgentNode.objects.create(graph=flow, **grant) for _ in range(4)]
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

    # The first save of a process also fills the content type cache; leave that out.
    saved_queries("warm-up-flow", {})
    ungranted = saved_queries("ungranted-flow", {})
    granted = saved_queries("granted-flow", RW_GRANT)

    # Steering is compared against surfaces and tools loaded for all nodes at once.
    assert granted == ungranted


# ---- recycle-bin restores come back detached --------------------------------


@pytest.mark.django_db
def test_a_restored_tool_is_not_reattached_to_the_surfaces_of_a_granted_node(
    acme, flow, surface, admin_client
):
    from tables.services.storage_grants.tool_lock import grant_locks_for_tools

    tool = _tool(acme)
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
    AgentNode.objects.create(graph=flow, **RW_GRANT).surface_list.add(surface)
    assert grant_locks_for_tools([tool.pk], acme.pk)

    assert admin_client.delete(f"/api/python-code-tool/{tool.pk}/").status_code == 204
    restored = admin_client.post(f"/api/python-code-tool/{tool.pk}/restore/", format="json")

    assert restored.status_code == status.HTTP_200_OK, restored.content
    assert PythonCodeTool.objects.filter(pk=tool.pk).exists()
    assert not SurfacePythonTool.objects.filter(python_tool=tool).exists()
    assert grant_locks_for_tools([tool.pk], acme.pk) == {}


@pytest.mark.django_db
def test_a_restored_surface_and_a_restored_agent_do_not_come_back_on_a_granted_node(
    acme, flow, surface, agent, admin_client
):
    node = TaskNode.objects.create(graph=flow, agent_definition=agent, **RW_GRANT)
    node.surface_list.add(surface)

    assert admin_client.delete(f"/api/surfaces/{surface.pk}/").status_code == 204
    assert admin_client.delete(f"/api/agent-definitions/{agent.pk}/").status_code == 204
    assert admin_client.post(f"/api/surfaces/{surface.pk}/restore/", format="json").status_code == 200
    assert (
        admin_client.post(f"/api/agent-definitions/{agent.pk}/restore/", format="json").status_code
        == 200
    )

    node.refresh_from_db()
    assert node.agent_definition_id is None
    assert not node.surface_list.exists()
