"""
Task and agent nodes reference surfaces (`surface_list`) and own an inline surface.
A caller without surfaces READ must neither see that data on any node response
(graph detail, node detail, bulk-save response, combined surface) nor change it
through a write: the editor posts back whatever it was shown, so a hidden field
echoed as empty must not wipe the node's surfaces, and an id the caller cannot read
must not be attached.
"""

import pytest
from django.urls import reverse
from rest_framework import status

from agents.models import AgentDefinition, AgentInlineSurface, InlineSurface, Surface
from rbac.access.catalog import grantable_bits_for
from rbac.models.enums import Permission, ResourceType
from tables.models.graph_models import AgentNode, TaskNode
from tests.fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import client_as, custom_role_user  # noqa: F401


def _every_permission_except(resource_type: ResourceType, action: Permission) -> dict:
    permissions = {resource: grantable_bits_for(resource.value) for resource in ResourceType}
    permissions[resource_type] &= ~int(action)
    return permissions


@pytest.fixture
def client_without_surface_read(client_as, custom_role_user, default_org):
    user = custom_role_user(
        default_org,
        "no-surface-read@example.com",
        _every_permission_except(ResourceType.SURFACES, Permission.READ),
    )
    client = client_as(user)
    client.credentials(HTTP_X_ORGANIZATION_ID=str(default_org.id))
    return client


@pytest.fixture
def shared_surface(default_org) -> Surface:
    return Surface.objects.create(org=default_org, name="visibility-shared-surface")


@pytest.fixture
def task_node_with_surfaces(graph, shared_surface) -> TaskNode:
    node = TaskNode.objects.create(graph=graph, node_name="task-with-surfaces")
    node.surface_list.set([shared_surface])
    InlineSurface.objects.create(task_node=node, instructions="task secret")
    return node


@pytest.fixture
def agent_node_with_surfaces(graph, shared_surface) -> AgentNode:
    node = AgentNode.objects.create(graph=graph, node_name="agent-with-surfaces")
    node.surface_list.set([shared_surface])
    AgentInlineSurface.objects.create(agent_node=node, instructions="agent secret")
    return node


def _assert_surfaces_hidden(node_data: dict) -> None:
    assert node_data["surface_list"] == []
    assert node_data["inline_surface"] is None


def _save(client, graph, payload):
    return client.post(
        reverse("graphs-save-flow", args=[graph.id]),
        {"save_version": graph.save_version, **payload},
        format="json",
    )


@pytest.mark.django_db
def test_graph_detail_hides_node_surfaces_without_surface_read(
    client_without_surface_read, graph, task_node_with_surfaces, agent_node_with_surfaces
):
    response = client_without_surface_read.get(reverse("graphs-detail", args=[graph.id]))

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_surfaces_hidden(response.data["task_node_list"][0])
    _assert_surfaces_hidden(response.data["agent_node_list"][0])


@pytest.mark.django_db
def test_graph_detail_shows_node_surfaces_with_surface_read(
    auth_client, graph, shared_surface, task_node_with_surfaces, agent_node_with_surfaces
):
    response = auth_client.get(reverse("graphs-detail", args=[graph.id]))

    assert response.status_code == status.HTTP_200_OK, response.content
    for node_data in (response.data["task_node_list"][0], response.data["agent_node_list"][0]):
        assert node_data["surface_list"] == [shared_surface.id]
        assert node_data["inline_surface"] is not None


@pytest.mark.django_db
def test_node_detail_hides_surfaces_without_surface_read(
    client_without_surface_read, task_node_with_surfaces, agent_node_with_surfaces
):
    task_response = client_without_surface_read.get(f"/api/tasknodes/{task_node_with_surfaces.id}/")
    agent_response = client_without_surface_read.get(
        f"/api/agentnodes/{agent_node_with_surfaces.id}/"
    )

    assert task_response.status_code == status.HTTP_200_OK, task_response.content
    assert agent_response.status_code == status.HTTP_200_OK, agent_response.content
    _assert_surfaces_hidden(task_response.data)
    _assert_surfaces_hidden(agent_response.data)


@pytest.mark.django_db
@pytest.mark.parametrize("route", ["tasknodes", "agentnodes"])
def test_combine_requires_surface_read(
    route,
    client_without_surface_read,
    auth_client,
    task_node_with_surfaces,
    agent_node_with_surfaces,
):
    node = task_node_with_surfaces if route == "tasknodes" else agent_node_with_surfaces
    url = f"/api/{route}/{node.id}/combine/"

    denied = client_without_surface_read.get(url)
    allowed = auth_client.get(url)

    assert denied.status_code == status.HTTP_403_FORBIDDEN, denied.content
    assert "secret" not in denied.content.decode()
    assert allowed.status_code == status.HTTP_200_OK, allowed.content


@pytest.mark.django_db
def test_bulk_save_without_surface_read_keeps_node_surfaces(
    client_without_surface_read,
    graph,
    shared_surface,
    task_node_with_surfaces,
    agent_node_with_surfaces,
):
    # What the editor posts back after a load that hid the surfaces.
    hidden_echo = {"surface_list": [], "inline_surface": None}
    response = _save(
        client_without_surface_read,
        graph,
        {
            "task_node_list": [
                {
                    "id": task_node_with_surfaces.id,
                    "graph": graph.id,
                    "node_name": "task-renamed",
                    **hidden_echo,
                }
            ],
            "agent_node_list": [
                {
                    "id": agent_node_with_surfaces.id,
                    "graph": graph.id,
                    "node_name": "agent-renamed",
                    **hidden_echo,
                }
            ],
        },
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    _assert_surfaces_hidden(response.data["task_node_list"][0])
    _assert_surfaces_hidden(response.data["agent_node_list"][0])
    for node in (task_node_with_surfaces, agent_node_with_surfaces):
        node.refresh_from_db()
        assert node.node_name.endswith("-renamed")
        assert list(node.surface_list.values_list("id", flat=True)) == [shared_surface.id]
    assert InlineSurface.objects.filter(task_node=task_node_with_surfaces).exists()
    assert AgentInlineSurface.objects.filter(agent_node=agent_node_with_surfaces).exists()


@pytest.mark.django_db
def test_bulk_save_without_surface_read_cannot_attach_or_probe_surfaces(
    client_without_surface_read, graph, shared_surface
):
    missing_surface_id = shared_surface.id + 1000
    response = _save(
        client_without_surface_read,
        graph,
        {
            "task_node_list": [
                {
                    "graph": graph.id,
                    "node_name": "task-new",
                    # A missing id must not answer differently from a real one.
                    "surface_list": [shared_surface.id, missing_surface_id],
                    "inline_surface": {"instructions": "injected"},
                }
            ],
        },
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    node = TaskNode.objects.get(graph=graph, node_name="task-new")
    assert not node.surface_list.exists()
    assert not InlineSurface.objects.filter(task_node=node).exists()


@pytest.mark.django_db
def test_node_patch_without_surface_read_leaves_surfaces(
    client_without_surface_read, shared_surface, task_node_with_surfaces
):
    response = client_without_surface_read.patch(
        f"/api/tasknodes/{task_node_with_surfaces.id}/",
        {"surface_list": [], "inline_surface": None},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    task_node_with_surfaces.refresh_from_db()
    assert list(task_node_with_surfaces.surface_list.values_list("id", flat=True)) == [
        shared_surface.id
    ]
    assert InlineSurface.objects.filter(task_node=task_node_with_surfaces).exists()


@pytest.mark.django_db
def test_agent_change_rejected_without_naming_hidden_surfaces(
    client_without_surface_read, default_org, graph
):
    owner = AgentDefinition.objects.create(org=default_org, name="visibility-owner")
    other = AgentDefinition.objects.create(org=default_org, name="visibility-other")
    owned_surface = Surface.objects.create(
        org=default_org, name="visibility-owned-surface", owner_agent=owner
    )
    node = TaskNode.objects.create(graph=graph, node_name="task-owned", agent_definition=owner)
    node.surface_list.set([owned_surface])

    response = _save(
        client_without_surface_read,
        graph,
        {
            "task_node_list": [
                {
                    "id": node.id,
                    "graph": graph.id,
                    "node_name": node.node_name,
                    "agent_definition": other.id,
                }
            ],
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
    body = response.content.decode()
    assert "agent_definition" in body
    assert f"Surface {owned_surface.id}" not in body
    node.refresh_from_db()
    assert node.agent_definition_id == owner.id
