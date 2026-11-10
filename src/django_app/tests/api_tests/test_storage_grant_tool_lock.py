"""Editing a Python tool's code is locked by the grants of the flow nodes that use the tool.

A node's grant covers its tools, so whoever changes a tool's code changes what a granted
node runs with the node's storage account. The lock reads the usage of the tool through
catalog surfaces, an agent's default surfaces and the node's own inline surface.
"""

import pytest
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
from rbac.models.enums import Permission, ResourceType
from tables.models import Graph, PythonCode, PythonCodeTool
from tables.models.graph_models import AgentNode, TaskNode
from tests.custom_role_fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

ALL = Permission.CREATE | Permission.READ | Permission.UPDATE | Permission.DELETE
NEW_CODE = {"python_code": {"code": "def main(): return 2", "entrypoint": "main"}}


def _tool(acme, name="tool"):
    return PythonCodeTool.objects.create(
        org=acme,
        name=name,
        description="d",
        variables=[],
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        built_in=False,
    )


def _grants(read, write, delete):
    return {
        "storage_grant_read": read,
        "storage_grant_write": write,
        "storage_grant_delete": delete,
    }


def _use_inline_on_task(graph, tool, grants):
    node = TaskNode.objects.create(graph=graph, **grants)
    inline = InlineSurface.objects.create(task_node=node)
    InlineSurfacePythonTool.objects.create(inline_surface=inline, python_tool=tool, mode=ToolMode.ALLOW)
    return node


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="tool-flow", org=acme)


@pytest.fixture
def tool(acme):
    return _tool(acme)


@pytest.fixture
def no_files_client(client_as, custom_role_user, acme):
    client = client_as(custom_role_user(acme, "tool-nofiles@example.com", {ResourceType.TOOLS: ALL}))
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


@pytest.fixture
def admin_client(client_as, admin_acme, acme):
    client = client_as(admin_acme)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.id))
    return client


def _use_via_catalog_surface(acme, graph, tool, grants):
    surface = Surface.objects.create(org=acme, name="shared", owner_agent=None)
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
    node = AgentNode.objects.create(graph=graph, **grants)
    node.surface_list.add(surface)
    return node


def _use_via_agent_default(acme, graph, tool, grants):
    agent = AgentDefinition.objects.create(
        org=acme, name="agent", instruction_list=[{"name": "i.md", "content": "x"}]
    )
    surface = Surface.objects.create(org=acme, name="agent-surface", owner_agent=None)
    SurfacePythonTool.objects.create(surface=surface, python_tool=tool, mode=ToolMode.ALLOW)
    AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface, place="all")
    return TaskNode.objects.create(graph=graph, agent_definition=agent, **grants)


def _use_via_agent_inline(acme, graph, tool, grants):
    node = AgentNode.objects.create(graph=graph, **grants)
    inline = AgentInlineSurface.objects.create(agent_node=node)
    AgentInlineSurfacePythonTool.objects.create(
        agent_inline_surface=inline, python_tool=tool, mode=ToolMode.ALLOW
    )
    return node


USAGES = {
    "task-inline-surface": lambda acme, graph, tool, grants: _use_inline_on_task(graph, tool, grants),
    "agent-inline-surface": _use_via_agent_inline,
    "attached-catalog-surface": _use_via_catalog_surface,
    "agents-default-surface": _use_via_agent_default,
}


@pytest.mark.django_db
@pytest.mark.parametrize("usage", list(USAGES))
def test_editing_the_code_of_a_tool_a_granted_node_uses_needs_that_nodes_permissions(
    usage, acme, flow, tool, no_files_client, admin_client
):
    USAGES[usage](acme, flow, tool, _grants(True, False, True))

    refused = no_files_client.patch(f"/api/python-code-tool/{tool.pk}/", NEW_CODE, format="json")
    allowed = admin_client.patch(f"/api/python-code-tool/{tool.pk}/", NEW_CODE, format="json")

    assert refused.status_code == status.HTTP_403_FORBIDDEN, refused.content
    assert refused.data["message"] == (
        "This code runs with Files: Read, Files: Delete, which you don't have. "
        "Contact an admin to change it."
    )
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    tool.python_code.refresh_from_db()
    assert tool.python_code.code == "def main(): return 2"


@pytest.mark.django_db
def test_a_refused_edit_leaves_the_tool_as_it_was(acme, flow, tool, no_files_client):
    _use_inline_on_task(flow, tool, _grants(True, False, False))

    no_files_client.patch(f"/api/python-code-tool/{tool.pk}/", NEW_CODE, format="json")

    tool.python_code.refresh_from_db()
    assert tool.python_code.code == "def main(): return 1"


@pytest.mark.django_db
@pytest.mark.parametrize(
    "grants", [None, (False, False, False)], ids=["not-configured", "granted-nothing"]
)
def test_a_tool_used_only_by_ungranted_nodes_is_not_locked(
    grants, acme, flow, tool, no_files_client
):
    node_grants = {} if grants is None else _grants(*grants)
    _use_inline_on_task(flow, tool, node_grants)

    response = no_files_client.patch(f"/api/python-code-tool/{tool.pk}/", NEW_CODE, format="json")

    assert response.status_code == status.HTTP_200_OK, response.content


@pytest.mark.django_db
def test_edits_that_do_not_touch_the_code_are_free_and_so_is_an_unchanged_resend(
    acme, flow, tool, no_files_client
):
    _use_inline_on_task(flow, tool, _grants(True, True, True))

    rename = no_files_client.patch(f"/api/python-code-tool/{tool.pk}/", {"description": "new"}, format="json")
    resend = no_files_client.patch(
        f"/api/python-code-tool/{tool.pk}/",
        {"python_code": {"code": "def main(): return 1", "entrypoint": "main"}},
        format="json",
    )

    assert rename.status_code == status.HTTP_200_OK
    assert resend.status_code == status.HTTP_200_OK


@pytest.mark.django_db
def test_the_lock_unions_every_granted_node_using_the_tool(
    acme, flow, tool, no_files_client
):
    other_flow = Graph.objects.create(name="other-flow", org=acme)
    _use_inline_on_task(flow, tool, _grants(True, False, False))
    _use_via_agent_inline(acme, other_flow, tool, _grants(False, True, False))

    response = no_files_client.patch(f"/api/python-code-tool/{tool.pk}/", NEW_CODE, format="json")

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.data["missing_grants"] == ["read", "write"]


@pytest.mark.django_db
def test_the_tool_shows_what_locks_it_and_nothing_for_a_tool_no_granted_node_uses(
    acme, flow, tool, admin_client
):
    free_tool = _tool(acme, name="free")
    other_flow = Graph.objects.create(name="second-flow", org=acme)
    _use_inline_on_task(flow, tool, _grants(True, False, True))
    _use_via_agent_inline(acme, other_flow, tool, _grants(True, False, False))

    detail = admin_client.get(f"/api/python-code-tool/{tool.pk}/")
    listing = admin_client.get("/api/python-code-tool/")

    assert detail.data["storage_grant_lock"] == {
        "required_grants": ["read", "delete"],
        "required_permissions": ["Files: Read", "Files: Delete"],
        "flow_names": ["second-flow", "tool-flow"],
    }
    by_id = {row["id"]: row["storage_grant_lock"] for row in listing.data["results"]}
    assert by_id[tool.pk] == detail.data["storage_grant_lock"]
    assert by_id[free_tool.pk] is None


@pytest.mark.django_db
def test_listing_tools_computes_every_lock_in_one_pass(acme, flow, admin_client):
    from unittest.mock import patch

    from tables.serializers.model_serializers import python_serializers

    tools = [_tool(acme, name=f"tool-{index}") for index in range(5)]
    for tool in tools:
        _use_inline_on_task(flow, tool, _grants(True, False, False))

    with patch.object(
        python_serializers, "grant_locks_for_tools", wraps=python_serializers.grant_locks_for_tools
    ) as spy:
        response = admin_client.get("/api/python-code-tool/")

    assert response.status_code == status.HTTP_200_OK
    assert spy.call_count == 1
    assert all(row["storage_grant_lock"] is not None for row in response.data["results"])


@pytest.mark.django_db
def test_another_orgs_tool_is_a_404_not_a_403(acme, beta, flow, tool, client_as, custom_role_user):
    _use_inline_on_task(flow, tool, _grants(True, True, True))
    outsider = client_as(custom_role_user(beta, "tool-outsider@example.com", {ResourceType.TOOLS: ALL}))
    outsider.credentials(HTTP_X_ORGANIZATION_ID=str(beta.id))

    response = outsider.patch(f"/api/python-code-tool/{tool.pk}/", NEW_CODE, format="json")

    assert response.status_code == status.HTTP_404_NOT_FOUND


@pytest.mark.django_db
def test_changing_the_variables_of_a_tool_a_granted_node_uses_is_an_edit(
    acme, flow, tool, no_files_client, admin_client
):
    _use_inline_on_task(flow, tool, _grants(True, False, False))
    variables = [{"name": "path", "input_type": "user_input", "default_value": "/etc"}]

    refused = no_files_client.patch(
        f"/api/python-code-tool/{tool.pk}/", {"variables": variables}, format="json"
    )
    allowed = admin_client.patch(
        f"/api/python-code-tool/{tool.pk}/", {"variables": variables}, format="json"
    )
    resend = no_files_client.patch(
        f"/api/python-code-tool/{tool.pk}/", {"variables": variables}, format="json"
    )

    assert refused.status_code == status.HTTP_403_FORBIDDEN
    assert allowed.status_code == status.HTTP_200_OK, allowed.content
    assert resend.status_code == status.HTTP_200_OK
