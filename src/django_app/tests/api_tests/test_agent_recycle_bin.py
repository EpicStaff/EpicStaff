"""Agents go to the recycle bin with their own surfaces and settings, and come back on restore."""

import pytest

from rbac.models import Organization
from agents.models import AgentDefaultSurface, AgentDefinition, Surface, SurfacePythonTool, ToolMode
from tables.models import AgentNode, TaskNode
from tables.models.realtime_models import RealtimeAgentDefinition
from tables.services.recycle_bin.restore_service import RestoreService


def _results(response):
    body = response.data
    return body["results"] if isinstance(body, dict) and "results" in body else body


def _agent_with_owned_things(org, python_code_tool, name="Helper"):
    agent = AgentDefinition.objects.create(organization=org, name=name)
    owned_surface = Surface.objects.create(organization=org, name=f"{name} surface", owner_agent=agent)
    owned = [
        owned_surface,
        SurfacePythonTool.objects.create(surface=owned_surface, python_tool=python_code_tool, mode=ToolMode.ALLOW),
        AgentDefaultSurface.objects.create(agent_definition=agent, surface=owned_surface),
        RealtimeAgentDefinition.objects.create(agent_definition=agent),
    ]
    return agent, owned


@pytest.mark.django_db
class TestAgentGoesToTheRecycleBin:
    def test_delete_bins_the_agent_with_its_owned_rows(self, auth_client, default_org, python_code_tool):
        agent, owned = _agent_with_owned_things(default_org, python_code_tool)

        response = auth_client.delete(f"/api/agent-definitions/{agent.id}/")

        assert response.status_code == 204, response.data
        batch = AgentDefinition.all_objects.get(pk=agent.pk).soft_delete_batch
        assert batch is not None
        for row in owned:
            assert type(row).all_objects.get(pk=row.pk).soft_delete_batch == batch, type(row)
        assert agent.id not in {item["id"] for item in _results(auth_client.get("/api/agent-definitions/"))}

    def test_a_binned_agent_frees_its_name(self, default_org):
        AgentDefinition.objects.create(organization=default_org, name="Helper").delete()

        AgentDefinition.objects.create(organization=default_org, name="Helper")

    def test_flows_lose_the_deleted_agent(self, default_org, graph):
        agent = AgentDefinition.objects.create(organization=default_org, name="Helper")
        task_node = TaskNode.objects.create(graph=graph, node_name="task", agent_definition=agent)

        agent.delete()

        task_node.refresh_from_db()
        assert task_node.agent_definition_id is None


@pytest.mark.django_db
@pytest.mark.parametrize("method", ["get", "put", "patch", "delete"])
def test_a_binned_agent_is_not_reachable_by_id(auth_client, default_org, method):
    agent = AgentDefinition.objects.create(organization=default_org, name="Helper")
    agent.delete()

    response = getattr(auth_client, method)(f"/api/agent-definitions/{agent.id}/", {"name": "x"}, format="json")

    assert response.status_code == 404, (method, response.status_code)


@pytest.mark.django_db
class TestAgentRestore:
    def test_restore_brings_the_agent_back_with_its_owned_rows(self, default_org, python_code_tool):
        agent, owned = _agent_with_owned_things(default_org, python_code_tool)
        agent.delete()

        result = RestoreService.restore(AgentDefinition.all_objects.get(pk=agent.pk))

        assert result.renamed_from is None
        for row in [agent, *owned]:
            assert type(row).objects.filter(pk=row.pk).exists(), type(row)

    def test_restore_renames_the_agent_when_its_name_is_taken(self, default_org):
        agent = AgentDefinition.objects.create(organization=default_org, name="Helper")
        agent.delete()
        AgentDefinition.objects.create(organization=default_org, name="Helper")

        result = RestoreService.restore(AgentDefinition.all_objects.get(pk=agent.pk))

        assert result.object.name == "Helper #2"

    def test_restore_renames_an_owned_surface_whose_name_was_taken(self, default_org, python_code_tool):
        # The owned surface comes back with the agent, so its name needs the
        # same clash handling as the root's, or the restore hits the unique constraint.
        agent, owned = _agent_with_owned_things(default_org, python_code_tool)
        owned_surface = owned[0]
        agent.delete()
        Surface.objects.create(organization=default_org, name=owned_surface.name)

        RestoreService.restore(AgentDefinition.all_objects.get(pk=agent.pk))

        assert Surface.objects.get(pk=owned_surface.pk).name == f"{owned_surface.name} #2"


@pytest.mark.django_db
class TestOwnedSurfaceRestoredOnItsOwn:
    """Restoring an agent brings its own surface back as its own. Restoring the
    surface by itself while the agent is in the bin brings it back shared."""

    def test_the_surface_comes_back_shared_with_its_contents_and_the_agent_stays_binned(
        self, default_org, python_code_tool
    ):
        agent, (surface, tool_link, default_link, realtime) = _agent_with_owned_things(default_org, python_code_tool)
        agent.delete()

        RestoreService.restore(Surface.all_objects.get(pk=surface.pk))

        restored = Surface.objects.get(pk=surface.pk)
        assert restored.owner_agent_id is None
        assert SurfacePythonTool.objects.filter(pk=tool_link.pk).exists()
        assert AgentDefinition.deleted_objects.filter(pk=agent.pk).exists()
        # The agent's own rows stay with it in the bin.
        assert AgentDefaultSurface.deleted_objects.filter(pk=default_link.pk).exists()
        assert RealtimeAgentDefinition.deleted_objects.filter(pk=realtime.pk).exists()

    def test_restoring_the_agent_afterwards_links_it_to_the_shared_surface(self, default_org, python_code_tool):
        agent, (surface, _, default_link, _) = _agent_with_owned_things(default_org, python_code_tool)
        agent.delete()
        RestoreService.restore(Surface.all_objects.get(pk=surface.pk))

        RestoreService.restore(AgentDefinition.all_objects.get(pk=agent.pk))

        assert AgentDefinition.objects.filter(pk=agent.pk).exists()
        assert AgentDefaultSurface.objects.get(pk=default_link.pk).surface_id == surface.pk
        assert Surface.objects.get(pk=surface.pk).owner_agent_id is None

    def test_restoring_the_agent_first_keeps_the_surface_its_own(self, default_org, python_code_tool):
        agent, (surface, *_) = _agent_with_owned_things(default_org, python_code_tool)
        agent.delete()

        RestoreService.restore(AgentDefinition.all_objects.get(pk=agent.pk))

        assert Surface.objects.get(pk=surface.pk).owner_agent_id == agent.pk

    def test_a_surface_deleted_before_its_agent_also_comes_back_shared(self, default_org):
        agent = AgentDefinition.objects.create(organization=default_org, name="Helper")
        surface = Surface.objects.create(organization=default_org, name="Owned", owner_agent=agent)
        surface.delete()
        agent.delete()

        RestoreService.restore(Surface.all_objects.get(pk=surface.pk))

        assert Surface.objects.get(pk=surface.pk).owner_agent_id is None
        assert AgentDefinition.deleted_objects.filter(pk=agent.pk).exists()

    def test_purging_the_agent_keeps_the_surface_restored_as_shared(self, default_org, python_code_tool):
        agent, (surface, *_) = _agent_with_owned_things(default_org, python_code_tool)
        agent.delete()
        RestoreService.restore(Surface.all_objects.get(pk=surface.pk))

        AgentDefinition.all_objects.get(pk=agent.pk).purge()

        assert Surface.objects.filter(pk=surface.pk).exists()


@pytest.mark.django_db
def test_agent_nodes_lose_the_deleted_agent(default_org, graph):
    agent = AgentDefinition.objects.create(organization=default_org, name="Helper")
    agent_node = AgentNode.objects.create(graph=graph, node_name="agent", agent_definition=agent)

    agent.delete()

    agent_node.refresh_from_db()
    assert agent_node.agent_definition_id is None


@pytest.mark.django_db
def test_another_orgs_agent_cannot_be_deleted(auth_client):
    other_org = Organization.objects.create(name="Other org")
    agent = AgentDefinition.objects.create(organization=other_org, name="Theirs")

    response = auth_client.delete(f"/api/agent-definitions/{agent.id}/")

    assert response.status_code == 404, response.status_code
    assert AgentDefinition.objects.filter(pk=agent.pk).exists()


@pytest.mark.django_db
def test_restore_does_not_rename_one_batch_row_onto_another(default_org):
    # The batch holds "Foo" and "Foo #2", and a live "Foo" exists: renaming the
    # first to "Foo #2" would collide with the second one.
    agent = AgentDefinition.objects.create(organization=default_org, name="Helper")
    first = Surface.objects.create(organization=default_org, name="Foo", owner_agent=agent)
    second = Surface.objects.create(organization=default_org, name="Foo #2", owner_agent=agent)
    agent.delete()
    Surface.objects.create(organization=default_org, name="Foo")

    RestoreService.restore(AgentDefinition.all_objects.get(pk=agent.pk))

    restored_names = {Surface.objects.get(pk=first.pk).name, Surface.objects.get(pk=second.pk).name}
    assert len(restored_names) == 2
    assert "Foo" not in restored_names
