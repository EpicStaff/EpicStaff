"""Surfaces go to the recycle bin with their own contents, and come back on restore."""

import pytest

from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfaceKnowledge,
    SurfaceMcpTool,
    SurfacePythonTool,
    ToolMode,
)
from agents.models.agent_models import SurfacePlace
from tables.models import SourceCollection, TaskNode
from tables.models.mcp_models import McpTool
from tables.services.recycle_bin.restore_service import RestoreService


def _results(response):
    body = response.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _surface_with_contents(org, python_code_tool, name="Research"):
    surface = Surface.objects.create(organization=org, name=name)
    contents = [
        SurfacePythonTool.objects.create(surface=surface, python_tool=python_code_tool, mode=ToolMode.ALLOW),
        SurfaceMcpTool.objects.create(
            surface=surface,
            mcp_tool=McpTool.objects.create(name="Search", transport="http://mcp", tool_name="search", org=org),
            mode=ToolMode.ALLOW,
        ),
        SurfaceKnowledge.objects.create(
            surface=surface, collection=SourceCollection.objects.create(org=org, collection_name="KB")
        ),
    ]
    return surface, contents


@pytest.mark.django_db
class TestSurfaceGoesToTheRecycleBin:
    def test_delete_bins_the_surface_with_its_contents(self, auth_client, default_org, python_code_tool):
        surface, contents = _surface_with_contents(default_org, python_code_tool)

        response = auth_client.delete(f"/api/surfaces/{surface.id}/")

        assert response.status_code == 204, response.data
        batch = Surface.all_objects.get(pk=surface.pk).soft_delete_batch
        assert batch is not None
        for row in contents:
            assert type(row).all_objects.get(pk=row.pk).soft_delete_batch == batch, type(row)
        assert surface.id not in {item["id"] for item in _results(auth_client.get("/api/surfaces/"))}

    def test_a_binned_surface_frees_its_name(self, auth_client, default_org):
        Surface.objects.create(organization=default_org, name="Research").delete()

        response = auth_client.post("/api/surfaces/", {"name": "Research"}, format="json")

        assert response.status_code == 201, response.data

    def test_live_users_lose_their_link_to_the_deleted_surface(self, default_org, graph):
        surface = Surface.objects.create(organization=default_org, name="Shared")
        task_node = TaskNode.objects.create(graph=graph, node_name="task")
        task_node.surface_list.add(surface)
        agent = AgentDefinition.objects.create(organization=default_org, name="Helper")
        default_link = AgentDefaultSurface.objects.create(agent_definition=agent, surface=surface)

        surface.delete()

        assert task_node.surface_list.count() == 0
        assert not AgentDefaultSurface.all_objects.filter(pk=default_link.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_a_binned_surface_is_not_reachable_by_id(auth_client, default_org, method):
    surface = Surface.objects.create(organization=default_org, name="Research")
    surface.delete()

    response = getattr(auth_client, method)(f"/api/surfaces/{surface.id}/", {"name": "x"}, format="json")

    assert response.status_code == 404, (method, response.status_code)


@pytest.mark.django_db
class TestSurfaceRestore:
    def test_restore_brings_the_surface_back_with_its_contents(self, default_org, python_code_tool):
        surface, contents = _surface_with_contents(default_org, python_code_tool)
        surface.delete()

        result = RestoreService.restore(Surface.all_objects.get(pk=surface.pk))

        assert result.renamed_from is None
        for row in [surface, *contents]:
            assert type(row).objects.filter(pk=row.pk).exists(), type(row)

    def test_restore_renames_when_the_name_is_taken(self, default_org):
        surface = Surface.objects.create(organization=default_org, name="Research")
        surface.delete()
        Surface.objects.create(organization=default_org, name="Research")

        result = RestoreService.restore(Surface.all_objects.get(pk=surface.pk))

        assert result.renamed_from == "Research"
        assert result.object.name == "Research #2"


@pytest.mark.django_db
class TestAgentOwnedSurface:
    def test_the_owners_default_surface_rows_come_back_with_the_surface(self, default_org):
        # Hard-deleting the owner's own row would make a restored surface fall
        # back to "applies everywhere" instead of the place the owner chose.
        owner = AgentDefinition.objects.create(organization=default_org, name="Owner")
        other_agent = AgentDefinition.objects.create(organization=default_org, name="Other")
        surface = Surface.objects.create(organization=default_org, name="Owned", owner_agent=owner)
        owner_row = AgentDefaultSurface.objects.create(
            agent_definition=owner, surface=surface, place=SurfacePlace.CHAT
        )
        other_row = AgentDefaultSurface.objects.create(agent_definition=other_agent, surface=surface)

        batch = surface.delete()

        assert AgentDefaultSurface.all_objects.get(pk=owner_row.pk).soft_delete_batch == batch
        assert not AgentDefaultSurface.all_objects.filter(pk=other_row.pk).exists()

        RestoreService.restore(Surface.all_objects.get(pk=surface.pk))

        restored_row = AgentDefaultSurface.objects.get(pk=owner_row.pk)
        assert restored_row.place == SurfacePlace.CHAT

    def test_purging_the_owner_agent_removes_its_binned_surface(self, default_org, python_code_tool):
        owner = AgentDefinition.objects.create(organization=default_org, name="Owner")
        surface, contents = _surface_with_contents(default_org, python_code_tool, name="Owned")
        Surface.objects.filter(pk=surface.pk).update(owner_agent=owner)
        surface.refresh_from_db()
        surface.delete()
        owner.delete()

        AgentDefinition.all_objects.get(pk=owner.pk).purge()

        assert not Surface.all_objects.filter(pk=surface.pk).exists()
        for row in contents:
            assert not type(row).all_objects.filter(pk=row.pk).exists(), type(row)
