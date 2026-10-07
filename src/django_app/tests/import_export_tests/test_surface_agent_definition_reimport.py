"""
Re-importing the same flow export must reuse what an earlier import created --
tools, surfaces and agent definitions renamed on collision ("surf #2") -- and
must never modify a reused row: an agent definition whose owned or default
surfaces no longer match the file is copied, not rewired.
"""

import json

import pytest
from django.db.models import Count

from tests.fixtures import *  # noqa: F401,F403
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403

from agents.models import (
    AgentDefaultSurface,
    AgentDefinition,
    Surface,
    SurfaceMcpTool,
    SurfacePlace,
    SurfacePythonTool,
    ToolMode,
)
from tables.import_export.enums import EntityType
from tables.import_export.registry import entity_registry
from tables.import_export.services.partial_export_service import (
    GraphPartialExportService,
    NodeRef,
)
from tables.import_export.services.partial_import_service import PartialImportService
from tables.models import (
    AgentNode,
    Graph,
    McpTool,
    PythonCode,
    PythonCodeTool,
    StartNode,
)


@pytest.fixture
def agent_flow(default_org):
    """A flow whose AgentNode uses an agent definition owning surface "surf"
    (one python + one MCP tool) and holding the unowned "default_surf" as its
    default surface for the flow place."""
    python_tool = PythonCodeTool.objects.create(
        name="py",
        description="description",
        python_code=PythonCode.objects.create(
            code="def main(): return 1", entrypoint="main", libraries=""
        ),
        org=default_org,
    )
    mcp_tool = McpTool.objects.create(
        org=default_org,
        name="mcp",
        transport="https://example.com/mcp",
        tool_name="search",
    )
    agent = AgentDefinition.objects.create(
        organization=default_org,
        name="agent",
        description="description",
        instructions="instructions",
    )
    owned_surface = Surface.objects.create(
        organization=default_org,
        name="surf",
        instructions="owned surface",
        owner_agent=agent,
    )
    SurfacePythonTool.objects.create(
        surface=owned_surface, python_tool=python_tool, mode=ToolMode.DENY
    )
    SurfaceMcpTool.objects.create(
        surface=owned_surface, mcp_tool=mcp_tool, mode=ToolMode.ALLOW
    )
    default_surface = Surface.objects.create(
        organization=default_org,
        name="default_surf",
        instructions="default surface",
    )
    AgentDefaultSurface.objects.create(
        agent_definition=agent, surface=default_surface, place=SurfacePlace.FLOW
    )

    graph = Graph.objects.create(
        name="agent flow", metadata={"nodes": [], "edges": []}, org=default_org
    )
    StartNode.objects.create(graph=graph, variables={})
    agent_node = AgentNode.objects.create(
        graph=graph, node_name="agent_node_1", agent_definition=agent
    )

    return {
        "graph": graph,
        "agent": agent,
        "agent_node": agent_node,
        "owned_surface": owned_surface,
        "default_surface": default_surface,
        "python_tool": python_tool,
        "mcp_tool": mcp_tool,
    }


@pytest.fixture
def export_file(agent_flow, export_service):
    return json.dumps(export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id]))


@pytest.fixture
def import_file(import_service):
    def _import(file_content: str):
        id_mapper, _ = import_service.import_data(json.loads(file_content), EntityType.GRAPH)
        return id_mapper

    return _import


def _org_counts(org) -> dict:
    return {
        "python_tools": PythonCodeTool.objects.filter(org=org).count(),
        "mcp_tools": McpTool.objects.filter(org=org).count(),
        "surfaces": Surface.objects.filter(organization=org).count(),
        "agents": AgentDefinition.objects.filter(organization=org).count(),
        "default_surface_rows": AgentDefaultSurface.objects.filter(
            agent_definition__organization=org
        ).count(),
    }


def _surface_state(agent: AgentDefinition) -> tuple[set, set]:
    return (
        set(agent.owned_surfaces.values_list("id", flat=True)),
        set(agent.default_surfaces.values_list("surface_id", "place")),
    )


def _assert_no_agent_owns_two_surfaces(org):
    assert not (
        AgentDefinition.objects.filter(organization=org)
        .annotate(owned_count=Count("owned_surfaces"))
        .filter(owned_count__gt=1)
        .exists()
    )


@pytest.mark.django_db
class TestToolDeletedAfterExport:
    def test_repeated_imports_create_tools_surface_and_agent_once(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        old_python_tool_id = agent_flow["python_tool"].id
        old_mcp_tool_id = agent_flow["mcp_tool"].id
        old_surface_id = agent_flow["owned_surface"].id
        agent_flow["python_tool"].delete()
        agent_flow["mcp_tool"].delete()
        agent_state_before = _surface_state(agent)
        counts_before = _org_counts(default_org)

        first_id_mapper = import_file(export_file)
        later_id_mappers = [import_file(export_file), import_file(export_file)]

        counts_after = _org_counts(default_org)
        assert counts_after["python_tools"] == counts_before["python_tools"] + 1
        assert counts_after["mcp_tools"] == counts_before["mcp_tools"] + 1
        assert counts_after["surfaces"] == counts_before["surfaces"] + 1
        assert counts_after["agents"] == counts_before["agents"] + 1
        for id_mapper in later_id_mappers:
            for entity_type, old_id in (
                (EntityType.PYTHON_CODE_TOOL, old_python_tool_id),
                (EntityType.MCP_TOOL, old_mcp_tool_id),
                (EntityType.SURFACE, old_surface_id),
                (EntityType.AGENT_DEFINITION, agent.id),
            ):
                assert not id_mapper.was_created(entity_type, old_id)
                assert id_mapper.get(entity_type, old_id) == first_id_mapper.get(
                    entity_type, old_id
                )

        recreated_surface = Surface.objects.get(
            id=first_id_mapper.get(EntityType.SURFACE, old_surface_id)
        )
        assert recreated_surface.name == "surf #2"
        assert set(recreated_surface.python_tools.values_list("python_tool_id", flat=True)) == {
            first_id_mapper.get(EntityType.PYTHON_CODE_TOOL, old_python_tool_id)
        }
        assert set(recreated_surface.mcp_tools.values_list("mcp_tool_id", flat=True)) == {
            first_id_mapper.get(EntityType.MCP_TOOL, old_mcp_tool_id)
        }

        new_agent = AgentDefinition.objects.get(
            id=first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        )
        assert new_agent.name == "agent #2"
        assert recreated_surface.owner_agent_id == new_agent.id
        assert _surface_state(agent) == agent_state_before
        _assert_no_agent_owns_two_surfaces(default_org)

    def test_tool_entries_carry_no_timestamps_or_soft_delete_state(self, export_file):
        data = json.loads(export_file)
        tool_entries = [*data[EntityType.PYTHON_CODE_TOOL], *data[EntityType.MCP_TOOL]]

        for entry in tool_entries:
            assert not {
                "created_at",
                "updated_at",
                "is_soft_deleted",
                "soft_deleted_at",
            } & set(entry)


def _as_legacy_file(file_content: str) -> str:
    """Add the keys tool entries carried before the import serializers excluded them."""
    data = json.loads(file_content)
    for entity_type in (EntityType.PYTHON_CODE_TOOL, EntityType.MCP_TOOL):
        for entry in data[entity_type]:
            entry.update(
                {"created_at": "2020-01-01T00:00:00Z", "updated_at": "2020-01-02T00:00:00Z"}
            )
    for entry in data[EntityType.PYTHON_CODE_TOOL]:
        entry.update({"is_soft_deleted": False, "soft_deleted_at": None})
    return json.dumps(data)


@pytest.mark.django_db
class TestLegacyToolEntries:
    def test_existing_tools_reused_despite_stale_timestamps(
        self, agent_flow, export_file, import_file, default_org
    ):
        legacy_file = _as_legacy_file(export_file)
        counts_before = _org_counts(default_org)

        id_mapper = import_file(legacy_file)

        assert _org_counts(default_org) == counts_before
        assert id_mapper.get(EntityType.PYTHON_CODE_TOOL, agent_flow["python_tool"].id) == (
            agent_flow["python_tool"].id
        )
        assert id_mapper.get(EntityType.MCP_TOOL, agent_flow["mcp_tool"].id) == (
            agent_flow["mcp_tool"].id
        )

    def test_tools_deleted_after_export_created_once(
        self, agent_flow, export_file, import_file, default_org
    ):
        legacy_file = _as_legacy_file(export_file)
        agent_flow["python_tool"].delete()
        agent_flow["mcp_tool"].delete()
        counts_before = _org_counts(default_org)

        import_file(legacy_file)
        import_file(legacy_file)

        counts_after = _org_counts(default_org)
        assert counts_after["python_tools"] == counts_before["python_tools"] + 1
        assert counts_after["mcp_tools"] == counts_before["mcp_tools"] + 1
        assert counts_after["surfaces"] == counts_before["surfaces"] + 1
        assert counts_after["agents"] == counts_before["agents"] + 1

    @pytest.mark.parametrize(
        "field_name, stored_value, reused",
        [
            ("use_storage", True, False),
            ("use_storage", False, True),
            # variables has a callable JSONField default (list).
            ("variables", [{"name": "city", "description": "a city"}], False),
            ("variables", [], True),
        ],
    )
    def test_python_tool_missing_field_compared_to_model_default(
        self, agent_flow, export_file, import_file, field_name, stored_value, reused
    ):
        data = json.loads(export_file)
        del data[EntityType.PYTHON_CODE_TOOL][0][field_name]
        python_tool = agent_flow["python_tool"]
        setattr(python_tool, field_name, stored_value)
        python_tool.save(update_fields=[field_name])

        id_mapper = import_file(json.dumps(data))

        mapped_id = id_mapper.get(EntityType.PYTHON_CODE_TOOL, python_tool.id)
        assert (mapped_id == python_tool.id) is reused

    @pytest.mark.parametrize("stored_timeout, reused", [(60.0, False), (30.0, True)])
    def test_mcp_tool_missing_field_compared_to_model_default(
        self, agent_flow, export_file, import_file, stored_timeout, reused
    ):
        data = json.loads(export_file)
        del data[EntityType.MCP_TOOL][0]["timeout"]
        mcp_tool = agent_flow["mcp_tool"]
        mcp_tool.timeout = stored_timeout
        mcp_tool.save(update_fields=["timeout"])

        id_mapper = import_file(json.dumps(data))

        mapped_id = id_mapper.get(EntityType.MCP_TOOL, mcp_tool.id)
        assert (mapped_id == mcp_tool.id) is reused

    def test_soft_deleted_flag_in_file_is_ignored(
        self, agent_flow, export_file, import_file
    ):
        data = json.loads(_as_legacy_file(export_file))
        python_tool_entry = data[EntityType.PYTHON_CODE_TOOL][0]
        python_tool_entry.update(
            {"is_soft_deleted": True, "soft_deleted_at": "2020-01-03T00:00:00Z"}
        )
        agent_flow["python_tool"].delete()

        id_mapper = import_file(json.dumps(data))

        new_tool = PythonCodeTool.all_objects.get(
            id=id_mapper.get(EntityType.PYTHON_CODE_TOOL, python_tool_entry["id"])
        )
        assert new_tool.is_soft_deleted is False
        assert new_tool.soft_deleted_at is None


@pytest.mark.django_db
class TestBuiltInTool:
    def test_built_in_with_changed_code_copied_at_most_once(
        self, agent_flow, export_service, import_file, default_org
    ):
        built_in_tool = PythonCodeTool.objects.create(
            name="built_in_py",
            description="built-in",
            python_code=PythonCode.objects.create(
                code="def main(): return 'old'", entrypoint="main", libraries=""
            ),
            built_in=True,
        )
        SurfacePythonTool.objects.create(
            surface=agent_flow["owned_surface"], python_tool=built_in_tool, mode=ToolMode.ALLOW
        )
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        built_in_tool.python_code.code = "def main(): return 'new'"
        built_in_tool.python_code.save(update_fields=["code"])

        id_mappers = [import_file(export_file) for _ in range(3)]

        org_copies = PythonCodeTool.objects.filter(org=default_org, name__startswith="built_in_py")
        assert org_copies.count() == 1
        assert {
            id_mapper.get(EntityType.PYTHON_CODE_TOOL, built_in_tool.id) for id_mapper in id_mappers
        } == {org_copies.get().id}


@pytest.mark.django_db
class TestRenamedCopyReused:
    def test_edited_surface_copied_with_new_agent_and_reused_next_import(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        # The pre-existing "surf" now differs from the exported one.
        agent_flow["owned_surface"].python_tools.update(mode=ToolMode.ALLOW)
        agent_state_before = _surface_state(agent)

        first_id_mapper = import_file(export_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)

        old_surface_id = agent_flow["owned_surface"].id
        renamed_surface = Surface.objects.get(
            id=first_id_mapper.get(EntityType.SURFACE, old_surface_id)
        )
        new_agent_id = first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        assert renamed_surface.name == "surf #2"
        assert renamed_surface.owner_agent_id == new_agent_id
        assert AgentDefinition.objects.get(id=new_agent_id).name == "agent #2"
        assert _surface_state(agent) == agent_state_before

        assert second_id_mapper.get(EntityType.SURFACE, old_surface_id) == renamed_surface.id
        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == new_agent_id
        assert _org_counts(default_org) == counts_after_first_import
        assert not Surface.objects.filter(name="surf #3").exists()
        _assert_no_agent_owns_two_surfaces(default_org)

    def test_agent_definition_renamed_on_collision_is_reused_next_import(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        agent.description = "changed after export"
        agent.save(update_fields=["description"])
        agent_state_before = _surface_state(agent)
        agents_before = AgentDefinition.objects.filter(organization=default_org).count()

        first_id_mapper = import_file(export_file)
        second_id_mapper = import_file(export_file)

        renamed_agent = AgentDefinition.objects.get(
            id=first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        )
        assert renamed_agent.name == "agent #2"
        # "surf" was reused and stays with its owner; the copy cannot claim it.
        assert not renamed_agent.owned_surfaces.exists()
        assert _surface_state(agent) == agent_state_before
        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == renamed_agent.id
        assert (
            AgentDefinition.objects.filter(organization=default_org).count()
            == agents_before + 1
        )

    def test_python_tool_renamed_for_different_code_is_reused_next_import(
        self, agent_flow, export_file, import_file, default_org
    ):
        python_code = agent_flow["python_tool"].python_code
        python_code.code = "def main(): return 2"
        python_code.save(update_fields=["code"])

        first_id_mapper = import_file(export_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)

        old_tool_id = agent_flow["python_tool"].id
        renamed_tool_id = first_id_mapper.get(EntityType.PYTHON_CODE_TOOL, old_tool_id)
        assert PythonCodeTool.objects.get(id=renamed_tool_id).name == "py #2"
        assert second_id_mapper.get(EntityType.PYTHON_CODE_TOOL, old_tool_id) == renamed_tool_id
        assert _org_counts(default_org) == counts_after_first_import
        _assert_no_agent_owns_two_surfaces(default_org)

    def test_renamed_copy_in_another_org_is_not_reused(
        self, agent_flow, export_file, import_file, default_org, beta
    ):
        foreign_tool = McpTool.objects.create(
            org=beta,
            name="mcp #2",
            transport="https://example.com/mcp",
            tool_name="search",
        )
        old_tool_id = agent_flow["mcp_tool"].id
        agent_flow["mcp_tool"].delete()

        id_mapper = import_file(export_file)

        new_tool_id = id_mapper.get(EntityType.MCP_TOOL, old_tool_id)
        assert new_tool_id != foreign_tool.id
        assert McpTool.objects.get(id=new_tool_id).org_id == default_org.id


@pytest.mark.django_db
class TestAgentDefinitionSurfacesNeverRewired:
    def test_deleted_surfaces_recreated_for_a_new_agent(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        old_owned_surface_id = agent_flow["owned_surface"].id
        old_default_surface_id = agent_flow["default_surface"].id
        agent_flow["owned_surface"].delete()
        agent_flow["default_surface"].delete()
        agent_state_before = _surface_state(agent)

        id_mapper = import_file(export_file)

        new_agent = AgentDefinition.objects.get(
            id=id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        )
        assert new_agent.name == "agent #2"
        assert _surface_state(agent) == agent_state_before

        recreated_owned = Surface.objects.get(
            id=id_mapper.get(EntityType.SURFACE, old_owned_surface_id)
        )
        recreated_default = Surface.objects.get(
            id=id_mapper.get(EntityType.SURFACE, old_default_surface_id)
        )
        assert recreated_owned.name == "surf"
        assert recreated_owned.owner_agent_id == new_agent.id
        assert recreated_default.owner_agent_id is None
        assert _surface_state(new_agent) == (
            {recreated_owned.id},
            {(recreated_default.id, SurfacePlace.FLOW)},
        )

        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)
        assert _org_counts(default_org) == counts_after_first_import
        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == new_agent.id

    def test_agent_that_lost_its_surface_does_not_shadow_the_copy_on_reimport(
        self, agent_flow, export_file, import_file, default_org
    ):
        # Only the owned surface is deleted: the original agent keeps its
        # default surface, so on re-import it matches everything except the
        # owned surface -- the copy that owns the re-created one must win.
        agent = agent_flow["agent"]
        agent_flow["owned_surface"].delete()

        first_id_mapper = import_file(export_file)
        second_id_mapper = import_file(export_file)

        new_agent_id = first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        assert new_agent_id != agent.id
        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == new_agent_id

    def test_one_of_two_owned_surfaces_deleted(
        self, agent_flow, export_service, import_file, default_org
    ):
        agent = agent_flow["agent"]
        first_surface = agent_flow["owned_surface"]
        second_surface = Surface.objects.create(
            organization=default_org,
            name="surf_two",
            instructions="second owned surface",
            owner_agent=agent,
        )
        old_second_surface_id = second_surface.id
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        second_surface.delete()
        agent_state_before = _surface_state(agent)

        def _bound_agent_id(id_mapper) -> int:
            new_graph_id = id_mapper.get(EntityType.GRAPH, agent_flow["graph"].id)
            return AgentNode.objects.get(graph_id=new_graph_id).agent_definition_id

        first_id_mapper = import_file(export_file)

        recreated_second_surface = Surface.objects.get(
            id=first_id_mapper.get(EntityType.SURFACE, old_second_surface_id)
        )
        new_agent = AgentDefinition.objects.get(
            id=first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        )
        assert new_agent.name == "agent #2"
        assert first_id_mapper.get(EntityType.SURFACE, first_surface.id) == first_surface.id
        assert set(new_agent.owned_surfaces.values_list("id", flat=True)) == {
            recreated_second_surface.id
        }
        assert _surface_state(agent) == agent_state_before
        assert _bound_agent_id(first_id_mapper) == new_agent.id

        counts_after_first_import = _org_counts(default_org)
        later_id_mappers = [import_file(export_file), import_file(export_file)]

        # No agent owns both surfaces now: "surf" stays with the original and
        # the re-created "surf_two" with "agent #2", and neither may be rewired.
        # Both are equally large subset matches, so the newest row wins: every
        # re-import keeps the binding to "agent #2" that the first import chose
        # (it runs without "surf", which only the original owns).
        assert _org_counts(default_org) == counts_after_first_import
        for id_mapper in later_id_mappers:
            assert id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == new_agent.id
            assert _bound_agent_id(id_mapper) == new_agent.id
        assert _surface_state(agent) == agent_state_before

    def test_one_of_three_owned_surfaces_deleted_keeps_first_binding(
        self, agent_flow, export_service, import_file, default_org
    ):
        agent = agent_flow["agent"]
        extra_surfaces = [
            Surface.objects.create(
                organization=default_org,
                name=name,
                instructions=f"{name} instructions",
                owner_agent=agent,
            )
            for name in ("surf_two", "surf_three")
        ]
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        extra_surfaces[-1].delete()
        agent_state_before = _surface_state(agent)

        def _bound_agent_id(id_mapper) -> int:
            new_graph_id = id_mapper.get(EntityType.GRAPH, agent_flow["graph"].id)
            return AgentNode.objects.get(graph_id=new_graph_id).agent_definition_id

        first_id_mapper = import_file(export_file)
        new_agent = AgentDefinition.objects.get(
            id=first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        )
        assert new_agent.name == "agent #2"
        assert _bound_agent_id(first_id_mapper) == new_agent.id

        counts_after_first_import = _org_counts(default_org)
        later_id_mappers = [import_file(export_file), import_file(export_file)]

        # The original still owns two of the file's surfaces and "agent #2" one,
        # so preferring the larger subset would silently re-bind to the original;
        # the newest row keeps the first import's binding.
        assert _org_counts(default_org) == counts_after_first_import
        for id_mapper in later_id_mappers:
            assert _bound_agent_id(id_mapper) == new_agent.id
        assert _surface_state(agent) == agent_state_before

    def test_reused_shared_surface_is_not_claimed(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        shared_surface = agent_flow["owned_surface"]
        shared_surface.owner_agent = None
        shared_surface.save(update_fields=["owner_agent"])
        agent_state_before = _surface_state(agent)

        first_id_mapper = import_file(export_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)

        assert first_id_mapper.get(EntityType.SURFACE, shared_surface.id) == shared_surface.id
        shared_surface.refresh_from_db()
        assert shared_surface.owner_agent_id is None
        # The agent already holds everything create_entity could give it.
        assert first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == agent.id
        assert _surface_state(agent) == agent_state_before
        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == agent.id
        assert _org_counts(default_org) == counts_after_first_import

    def test_new_agent_does_not_claim_reused_shared_surface(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        shared_surface = agent_flow["owned_surface"]
        shared_surface.owner_agent = None
        shared_surface.save(update_fields=["owner_agent"])
        agent.description = "changed after export"
        agent.save(update_fields=["description"])

        first_id_mapper = import_file(export_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)

        new_agent_id = first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        assert new_agent_id != agent.id
        shared_surface.refresh_from_db()
        assert shared_surface.owner_agent_id is None
        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == new_agent_id
        assert _org_counts(default_org) == counts_after_first_import

    def test_created_surface_claimed_by_first_new_agent_only(
        self, agent_flow, export_file, import_file
    ):
        agent = agent_flow["agent"]
        old_owned_surface_id = agent_flow["owned_surface"].id
        agent_flow["owned_surface"].delete()
        data = json.loads(export_file)
        # A second agent in the same file that also claims the surface, imported
        # first because it is listed first.
        other_agent_entry = {
            **data[EntityType.AGENT_DEFINITION][0],
            "id": agent.id + 100000,
            "name": "other agent",
        }
        data[EntityType.AGENT_DEFINITION].insert(0, other_agent_entry)

        id_mapper = import_file(json.dumps(data))

        other_agent_id = id_mapper.get(EntityType.AGENT_DEFINITION, other_agent_entry["id"])
        recreated_owned = Surface.objects.get(
            id=id_mapper.get(EntityType.SURFACE, old_owned_surface_id)
        )
        assert recreated_owned.owner_agent_id == other_agent_id


@pytest.mark.django_db
class TestPartialImport:
    def test_deleted_owned_surface_recreated_for_a_new_agent(self, agent_flow, default_org):
        agent = agent_flow["agent"]
        old_owned_surface_id = agent_flow["owned_surface"].id
        export_result = GraphPartialExportService(entity_registry).export(
            [NodeRef(entity_type=EntityType.AGENT_NODE, node_id=agent_flow["agent_node"].id)],
            org_id=default_org.id,
        )
        assert not export_result.has_errors, export_result.errors
        partial_file = json.dumps(export_result.data)
        agent_flow["owned_surface"].delete()
        agent_state_before = _surface_state(agent)
        target_graph = Graph.objects.create(
            name="target flow", metadata={"nodes": [], "edges": []}, org=default_org
        )

        def _partial_import():
            return PartialImportService(entity_registry).import_data(
                json.loads(partial_file), target_graph, org_id=default_org.id
            )

        id_mapper = _partial_import()

        new_agent_id = id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        recreated_owned = Surface.objects.get(
            id=id_mapper.get(EntityType.SURFACE, old_owned_surface_id)
        )
        assert new_agent_id != agent.id
        assert recreated_owned.owner_agent_id == new_agent_id
        assert _surface_state(agent) == agent_state_before
        assert set(target_graph.agent_node_list.values_list("agent_definition_id", flat=True)) == {
            new_agent_id
        }

        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = _partial_import()
        assert _org_counts(default_org) == counts_after_first_import
        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == new_agent_id
