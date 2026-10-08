"""
Re-importing the same flow export must reuse what an earlier import created --
tools, surfaces and agent definitions renamed on collision ("surf #2") -- and
must never modify a reused row: an agent definition whose owned or default
surfaces no longer match the file is copied, not rewired.
"""

import json

import pytest
from django.db import connection
from django.db.models import Count
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import PermissionDenied, ValidationError

from rbac.access.effective import EffectivePermissions
from rbac.models.enums import Permission, ResourceType

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
from tables.import_export.id_mapper import IDMapper
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
        instruction_list=[{"name": "Instruction_1.md", "content": "instructions"}],
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

    @pytest.mark.parametrize("legacy_shape", ["without_entrypoint_and_kwargs", "blank_entrypoint"])
    def test_python_code_reused_on_reimport_as_create_stored_it(
        self, legacy_shape, agent_flow, export_file, import_file, default_org
    ):
        # create stores a missing or blank entrypoint as "main" and a missing
        # global_kwargs as {}; the lookup must compare against those values.
        data = json.loads(export_file)
        python_tool_entry = data[EntityType.PYTHON_CODE_TOOL][0]
        python_code = python_tool_entry["python_code"]
        if legacy_shape == "without_entrypoint_and_kwargs":
            del python_code["entrypoint"]
            del python_code["global_kwargs"]
        else:
            python_code["entrypoint"] = ""
        legacy_file = json.dumps(data)
        agent_flow["python_tool"].delete()
        tools_before = PythonCodeTool.objects.filter(org=default_org).count()

        first_id_mapper = import_file(legacy_file)
        second_id_mapper = import_file(legacy_file)

        created_tool_id = first_id_mapper.get(EntityType.PYTHON_CODE_TOOL, python_tool_entry["id"])
        created_code = PythonCodeTool.objects.get(id=created_tool_id).python_code
        assert created_code.entrypoint == "main"
        assert created_code.global_kwargs == {}
        assert (
            second_id_mapper.get(EntityType.PYTHON_CODE_TOOL, python_tool_entry["id"])
            == created_tool_id
        )
        assert PythonCodeTool.objects.filter(org=default_org).count() == tools_before + 1

    @pytest.mark.parametrize(
        "stored, exported, reused",
        [
            ({"global_kwargs": {"flag": 1}}, {"global_kwargs": {"flag": True}}, False),
            ({"global_kwargs": {"flag": 1}}, {"global_kwargs": {"flag": 1}}, True),
            ({"entrypoint": ""}, {"entrypoint": ""}, False),
            ({"code": "  def main(): return 1"}, {"code": "def main(): return 1"}, False),
            ({"code": "def main(): return 1\n\n"}, {"code": "def main(): return 1"}, True),
        ],
    )
    def test_python_code_reused_only_when_it_runs_the_same(
        self, stored, exported, reused, agent_flow, export_file, import_file
    ):
        python_tool = agent_flow["python_tool"]
        PythonCode.objects.filter(id=python_tool.python_code_id).update(**stored)
        data = json.loads(export_file)
        data[EntityType.PYTHON_CODE_TOOL][0]["python_code"].update(exported)

        id_mapper = import_file(json.dumps(data))

        mapped_id = id_mapper.get(EntityType.PYTHON_CODE_TOOL, python_tool.id)
        assert (mapped_id == python_tool.id) is reused

    def test_agent_entry_missing_defaulted_fields_reuses_the_agent(
        self, agent_flow, export_service, import_file, default_org
    ):
        # A missing key compares as the model default, which create stores.
        # Execution limits are left out: a missing one marks an older file and
        # takes the legacy value (normalize_legacy_agent_entry).
        agent = agent_flow["agent"]
        agent.description = ""
        agent.save(update_fields=["description"])
        data = json.loads(
            json.dumps(export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id]))
        )
        for field_name in ("description", "metadata"):
            del data[EntityType.AGENT_DEFINITION][0][field_name]
        counts_before = _org_counts(default_org)

        id_mapper = import_file(json.dumps(data))

        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == agent.id
        assert _org_counts(default_org) == counts_before


@pytest.mark.django_db
class TestLegacyAgentEntries:
    @pytest.mark.parametrize(
        "legacy_max_iter, stored_max_iter",
        [(None, 25), (-5, 1), (10**6, 90)],
        ids=["null", "below range", "above range"],
    )
    def test_legacy_agent_imports_and_is_reused_on_reimport(
        self, legacy_max_iter, stored_max_iter, agent_flow, export_file, import_file, default_org
    ):
        # A file from before named instructions and today's limits: one
        # instructions string, and a null or out-of-range execution limit.
        data = json.loads(export_file)
        agent_entry = data[EntityType.AGENT_DEFINITION][0]
        del agent_entry["instruction_list"]
        agent_entry["instructions"] = "legacy instructions"
        agent_entry["max_iter"] = legacy_max_iter
        legacy_file = json.dumps(data)

        first_id_mapper = import_file(legacy_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(legacy_file)

        imported_agent = AgentDefinition.objects.get(
            id=first_id_mapper.get(EntityType.AGENT_DEFINITION, agent_entry["id"])
        )
        assert imported_agent.instruction_list == [
            {"name": "Instruction_1.md", "content": "legacy instructions"}
        ]
        assert imported_agent.max_iter == stored_max_iter
        assert (
            second_id_mapper.get(EntityType.AGENT_DEFINITION, agent_entry["id"])
            == imported_agent.id
        )
        assert _org_counts(default_org) == counts_after_first_import


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
        # The copy owns its own "surf"; the original keeps its own.
        assert list(renamed_agent.owned_surfaces.values_list("name", "instructions")) == [
            ("surf #2", agent_flow["owned_surface"].instructions)
        ]
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
        first_surface_copy_id = first_id_mapper.get(EntityType.SURFACE, first_surface.id)
        assert new_agent.name == "agent #2"
        assert first_surface_copy_id != first_surface.id
        # The original no longer owns everything the file says, so the new agent
        # gets its own copy of both surfaces; the original is never rewired.
        assert set(new_agent.owned_surfaces.values_list("id", flat=True)) == {
            first_surface_copy_id,
            recreated_second_surface.id,
        }
        assert _surface_state(agent) == agent_state_before
        assert _bound_agent_id(first_id_mapper) == new_agent.id

        counts_after_first_import = _org_counts(default_org)
        later_id_mappers = [import_file(export_file), import_file(export_file)]

        # "agent #2" owns an equivalent of both surfaces and the original only
        # of one, so every re-import binds to "agent #2" again.
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

        # The original still owns two of the file's three surfaces; only
        # "agent #2" owns an equivalent of all three, so re-imports never
        # re-bind to the original.
        assert new_agent.owned_surfaces.count() == 3
        assert _org_counts(default_org) == counts_after_first_import
        for id_mapper in later_id_mappers:
            assert _bound_agent_id(id_mapper) == new_agent.id
        assert _surface_state(agent) == agent_state_before

    def test_equivalent_shared_surface_is_not_used_as_owned(
        self, agent_flow, export_file, import_file, default_org
    ):
        # The file says the agent owns "surf"; an identical shared "surf" exists
        # (e.g. left behind by an earlier import). Reusing it would leave the
        # agent without its surface, so the agent gets its own copy.
        agent = agent_flow["agent"]
        shared_surface = agent_flow["owned_surface"]
        shared_surface.owner_agent = None
        shared_surface.save(update_fields=["owner_agent"])
        agent_state_before = _surface_state(agent)

        first_id_mapper = import_file(export_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)

        new_agent_id = first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        surface_copy = Surface.objects.get(
            id=first_id_mapper.get(EntityType.SURFACE, shared_surface.id)
        )
        assert new_agent_id != agent.id
        assert surface_copy.id != shared_surface.id
        assert surface_copy.owner_agent_id == new_agent_id
        assert first_id_mapper.get_created_count(EntityType.SURFACE) == 1
        assert first_id_mapper.get_reused_count(EntityType.SURFACE) == 1
        assert first_id_mapper.get_created_count(EntityType.AGENT_DEFINITION) == 1
        shared_surface.refresh_from_db()
        assert shared_surface.owner_agent_id is None
        assert _surface_state(agent) == agent_state_before

        assert second_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == new_agent_id
        assert second_id_mapper.get(EntityType.SURFACE, shared_surface.id) == surface_copy.id
        assert second_id_mapper.get_created_count(EntityType.SURFACE) == 0
        assert second_id_mapper.get_created_count(EntityType.AGENT_DEFINITION) == 0
        assert _org_counts(default_org) == counts_after_first_import

    def test_equivalent_surface_owned_by_another_agent_is_not_used(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        old_owned_surface_id = agent_flow["owned_surface"].id
        agent_flow["owned_surface"].delete()
        other_agent = AgentDefinition.objects.create(
            organization=default_org, name="other agent", description="other"
        )
        other_surface = Surface.objects.create(
            organization=default_org,
            name="surf",
            instructions="owned surface",
            owner_agent=other_agent,
        )
        SurfacePythonTool.objects.create(
            surface=other_surface, python_tool=agent_flow["python_tool"], mode=ToolMode.DENY
        )
        SurfaceMcpTool.objects.create(
            surface=other_surface, mcp_tool=agent_flow["mcp_tool"], mode=ToolMode.ALLOW
        )
        other_agent_state_before = _surface_state(other_agent)

        first_id_mapper = import_file(export_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)

        new_agent_id = first_id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        surface_copy = Surface.objects.get(
            id=first_id_mapper.get(EntityType.SURFACE, old_owned_surface_id)
        )
        assert new_agent_id not in (agent.id, other_agent.id)
        assert surface_copy.id != other_surface.id
        assert surface_copy.owner_agent_id == new_agent_id
        other_surface.refresh_from_db()
        assert other_surface.owner_agent_id == other_agent.id
        assert _surface_state(other_agent) == other_agent_state_before
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


@pytest.mark.django_db
class TestOwnedSurfacesMatchedWithTheirAgent:
    @pytest.fixture
    def owned_surface_referenced_everywhere(self, agent_flow):
        """The agent node also lists the owned surface, and the agent holds it as
        a default surface for the chat place."""
        agent_flow["agent_node"].surface_list.set([agent_flow["owned_surface"]])
        AgentDefaultSurface.objects.create(
            agent_definition=agent_flow["agent"],
            surface=agent_flow["owned_surface"],
            place=SurfacePlace.CHAT,
        )
        return agent_flow

    def _imported_node(self, agent_flow, id_mapper) -> AgentNode:
        new_graph_id = id_mapper.get(EntityType.GRAPH, agent_flow["graph"].id)
        return AgentNode.objects.get(graph_id=new_graph_id)

    def test_unchanged_flow_reuses_agent_and_owned_surface(
        self, owned_surface_referenced_everywhere, export_service, import_file, default_org
    ):
        agent_flow = owned_surface_referenced_everywhere
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        counts_before = _org_counts(default_org)

        id_mapper = import_file(export_file)

        assert _org_counts(default_org) == counts_before
        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent_flow["agent"].id) == (
            agent_flow["agent"].id
        )
        owned_surface_id = agent_flow["owned_surface"].id
        assert id_mapper.get(EntityType.SURFACE, owned_surface_id) == owned_surface_id
        assert not id_mapper.was_created(EntityType.SURFACE, owned_surface_id)
        assert set(
            self._imported_node(agent_flow, id_mapper).surface_list.values_list("id", flat=True)
        ) == {owned_surface_id}

    def test_new_agent_references_point_at_its_own_surface_copy(
        self, owned_surface_referenced_everywhere, export_service, import_file
    ):
        agent_flow = owned_surface_referenced_everywhere
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        agent = agent_flow["agent"]
        agent.description = "changed after export"
        agent.save(update_fields=["description"])

        id_mapper = import_file(export_file)

        new_agent = AgentDefinition.objects.get(
            id=id_mapper.get(EntityType.AGENT_DEFINITION, agent.id)
        )
        surface_copy_id = id_mapper.get(EntityType.SURFACE, agent_flow["owned_surface"].id)
        assert set(new_agent.owned_surfaces.values_list("id", flat=True)) == {surface_copy_id}
        node = self._imported_node(agent_flow, id_mapper)
        assert node.agent_definition_id == new_agent.id
        assert set(node.surface_list.values_list("id", flat=True)) == {surface_copy_id}
        assert set(new_agent.default_surfaces.values_list("surface_id", "place")) == {
            (surface_copy_id, SurfacePlace.CHAT),
            (agent_flow["default_surface"].id, SurfacePlace.FLOW),
        }

    def test_agent_that_gained_a_surface_after_export_is_not_reused(
        self, agent_flow, export_file, import_file, default_org
    ):
        agent = agent_flow["agent"]
        Surface.objects.create(
            organization=default_org, name="added later", owner_agent=agent
        )

        id_mapper = import_file(export_file)

        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) != agent.id

    def test_content_identical_owned_surfaces_are_reused_as_they_are(
        self, agent_flow, export_service, import_file, default_org
    ):
        agent = agent_flow["agent"]
        owned_surface = agent_flow["owned_surface"]
        twin = Surface.objects.create(
            organization=default_org,
            name="surf #2",
            instructions=owned_surface.instructions,
            owner_agent=agent,
        )
        SurfacePythonTool.objects.create(
            surface=twin, python_tool=agent_flow["python_tool"], mode=ToolMode.DENY
        )
        SurfaceMcpTool.objects.create(
            surface=twin, mcp_tool=agent_flow["mcp_tool"], mode=ToolMode.ALLOW
        )
        AgentDefaultSurface.objects.create(
            agent_definition=agent, surface=twin, place=SurfacePlace.CHAT
        )
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        counts_before = _org_counts(default_org)

        id_mapper = import_file(export_file)

        assert _org_counts(default_org) == counts_before
        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) == agent.id
        assert id_mapper.get_created_count(EntityType.AGENT_DEFINITION) == 0
        assert id_mapper.get_created_count(EntityType.SURFACE) == 0
        assert id_mapper.get(EntityType.SURFACE, owned_surface.id) == owned_surface.id
        assert id_mapper.get(EntityType.SURFACE, twin.id) == twin.id

    def test_shared_entry_never_reuses_an_owned_surface(
        self, agent_flow, export_file, import_file, default_org
    ):
        # "default_surf" is shared in the file. The only equivalent row left in
        # the org is owned by an unrelated agent; using it would give the
        # imported agent another agent's owned surface as a default.
        old_default_surface_id = agent_flow["default_surface"].id
        agent_flow["default_surface"].delete()
        unrelated_agent = AgentDefinition.objects.create(
            organization=default_org, name="unrelated agent"
        )
        unrelated_surface = Surface.objects.create(
            organization=default_org,
            name="default_surf #2",
            instructions="default surface",
            owner_agent=unrelated_agent,
        )
        unrelated_agent_state_before = _surface_state(unrelated_agent)

        first_id_mapper = import_file(export_file)
        counts_after_first_import = _org_counts(default_org)
        second_id_mapper = import_file(export_file)

        new_shared_surface = Surface.objects.get(
            id=first_id_mapper.get(EntityType.SURFACE, old_default_surface_id)
        )
        assert new_shared_surface.id != unrelated_surface.id
        assert new_shared_surface.owner_agent_id is None
        unrelated_surface.refresh_from_db()
        assert unrelated_surface.owner_agent_id == unrelated_agent.id
        assert _surface_state(unrelated_agent) == unrelated_agent_state_before
        assert (
            second_id_mapper.get(EntityType.SURFACE, old_default_surface_id)
            == new_shared_surface.id
        )
        assert _org_counts(default_org) == counts_after_first_import

    def test_renamed_owned_surface_with_unchanged_content_is_reused(
        self, agent_flow, export_file, import_file, default_org
    ):
        # Owned surfaces compare by content only: renaming one after export
        # changes nothing the agent runs with.
        owned_surface = agent_flow["owned_surface"]
        owned_surface.name = "renamed after export"
        owned_surface.save(update_fields=["name"])
        counts_before = _org_counts(default_org)

        id_mapper = import_file(export_file)

        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent_flow["agent"].id) == (
            agent_flow["agent"].id
        )
        assert id_mapper.get(EntityType.SURFACE, owned_surface.id) == owned_surface.id
        assert _org_counts(default_org) == counts_before

    def test_agent_with_another_shared_default_surface_is_not_reused(
        self, agent_flow, export_file, import_file, default_org
    ):
        other_shared_surface = Surface.objects.create(
            organization=default_org, name="other shared", instructions="other"
        )
        AgentDefaultSurface.objects.filter(agent_definition=agent_flow["agent"]).update(
            surface=other_shared_surface
        )

        id_mapper = import_file(export_file)

        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent_flow["agent"].id) != (
            agent_flow["agent"].id
        )

    def test_agent_with_owned_default_at_another_place_is_not_reused(
        self, owned_surface_referenced_everywhere, export_service, import_file
    ):
        agent_flow = owned_surface_referenced_everywhere
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        AgentDefaultSurface.objects.filter(
            agent_definition=agent_flow["agent"], surface=agent_flow["owned_surface"]
        ).update(place=SurfacePlace.REALTIME)

        id_mapper = import_file(export_file)

        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent_flow["agent"].id) != (
            agent_flow["agent"].id
        )

    def test_each_owned_surface_needs_its_own_equivalent(
        self, agent_flow, export_service, import_file, default_org
    ):
        # "surf #2" and "surf #3" share a base name, so each also matches the
        # other's name. Once "surf #3" is edited, the agent owns only one
        # equivalent of the two identical exported surfaces.
        agent = agent_flow["agent"]
        agent_flow["owned_surface"].delete()
        twins = [
            Surface.objects.create(
                organization=default_org, name=name, instructions="twin", owner_agent=agent
            )
            for name in ("surf #2", "surf #3")
        ]
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        twins[1].instructions = "edited after export"
        twins[1].save(update_fields=["instructions"])

        id_mapper = import_file(export_file)

        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent.id) != agent.id


def _effective_permissions(*resources) -> EffectivePermissions:
    return EffectivePermissions(
        is_superadmin=False,
        role=None,
        by_resource={
            resource: int(Permission.CREATE | Permission.READ) for resource in resources
        },
    )


@pytest.mark.django_db
class TestOwnedSurfaceCreatePermission:
    def test_import_denied_without_surfaces_create(
        self, agent_flow, export_file, import_service, default_org
    ):
        agent_flow["owned_surface"].delete()
        counts_before = _org_counts(default_org)
        graphs_before = Graph.objects.count()

        with pytest.raises(PermissionDenied) as exc:
            import_service.import_data(
                json.loads(export_file),
                EntityType.GRAPH,
                effective_permissions=_effective_permissions(
                    ResourceType.FLOWS, ResourceType.AGENTS
                ),
            )

        assert "surfaces" in str(exc.value)
        assert _org_counts(default_org) == counts_before
        assert Graph.objects.count() == graphs_before

    def test_import_allowed_with_surfaces_create(
        self, agent_flow, export_file, import_service, default_org
    ):
        agent_flow["owned_surface"].delete()
        surfaces_before = _org_counts(default_org)["surfaces"]

        import_service.import_data(
            json.loads(export_file),
            EntityType.GRAPH,
            effective_permissions=_effective_permissions(
                ResourceType.FLOWS, ResourceType.AGENTS, ResourceType.SURFACES
            ),
        )

        assert _org_counts(default_org)["surfaces"] == surfaces_before + 1

    def test_partial_import_denied_without_surfaces_create(self, agent_flow, default_org):
        export_result = GraphPartialExportService(entity_registry).export(
            [NodeRef(entity_type=EntityType.AGENT_NODE, node_id=agent_flow["agent_node"].id)],
            org_id=default_org.id,
        )
        assert not export_result.has_errors, export_result.errors
        agent_flow["owned_surface"].delete()
        target_graph = Graph.objects.create(
            name="target flow", metadata={"nodes": [], "edges": []}, org=default_org
        )
        counts_before = _org_counts(default_org)

        with pytest.raises(PermissionDenied) as exc:
            PartialImportService(entity_registry).import_data(
                json.loads(json.dumps(export_result.data)),
                target_graph,
                org_id=default_org.id,
                effective_permissions=_effective_permissions(ResourceType.AGENTS),
            )

        assert "surfaces" in str(exc.value)
        assert _org_counts(default_org) == counts_before
        assert not target_graph.agent_node_list.exists()


def _flow_with_identical_owned_surfaces(org, agent_name: str, surface_count: int) -> Graph:
    """A flow whose agent owns `surface_count` content-identical surfaces named
    "<agent_name> surf", "<agent_name> surf #2", ... -- one name family."""
    agent = AgentDefinition.objects.create(organization=org, name=agent_name)
    base_name = f"{agent_name} surf"
    Surface.objects.bulk_create(
        [
            Surface(
                organization=org,
                name=base_name if number == 1 else f"{base_name} #{number}",
                instructions="identical",
                owner_agent=agent,
            )
            for number in range(1, surface_count + 1)
        ]
    )
    graph = Graph.objects.create(
        name=f"{agent_name} flow", metadata={"nodes": [], "edges": []}, org=org
    )
    AgentNode.objects.create(graph=graph, node_name="agent_node", agent_definition=agent)
    return graph


@pytest.mark.django_db
class TestOwnedSurfacePairingCost:
    def test_reimport_query_count_does_not_grow_with_owned_surfaces(
        self, export_service, import_file, default_org
    ):
        def _reimport_query_count(agent_name: str, surface_count: int) -> int:
            graph = _flow_with_identical_owned_surfaces(default_org, agent_name, surface_count)
            export_file = json.dumps(export_service.export_entities(EntityType.GRAPH, [graph.id]))
            counts_before = _org_counts(default_org)
            with CaptureQueriesContext(connection) as queries:
                id_mapper = import_file(export_file)
            assert _org_counts(default_org) == counts_before
            assert id_mapper.get_created_count(EntityType.SURFACE) == 0
            return len(queries)

        assert _reimport_query_count("small", 5) == _reimport_query_count("large", 300)


@pytest.mark.django_db
class TestDuplicateAgentDefinitionIds:
    def test_file_listing_an_agent_id_twice_is_rejected(
        self, agent_flow, export_file, import_service, default_org
    ):
        data = json.loads(export_file)
        agent_entry = data[EntityType.AGENT_DEFINITION][0]
        data[EntityType.AGENT_DEFINITION].append(
            {**agent_entry, "name": "same id, other surfaces", "owned_surfaces": []}
        )
        counts_before = _org_counts(default_org)
        graphs_before = Graph.objects.count()

        with pytest.raises(ValidationError) as exc:
            import_service.import_data(data, EntityType.GRAPH)

        assert str(agent_entry["id"]) in str(exc.value.detail)
        assert _org_counts(default_org) == counts_before
        assert Graph.objects.count() == graphs_before


@pytest.mark.django_db
class TestHandEditedSurfaceValues:
    """A number for instructions is stored as text by the import serializer and
    compared as that text, so it imports once and is reused after. A mode the
    surface tools cannot store is rejected before anything is written."""

    def _set_instructions(self, agent_flow, data):
        self._owned_entry(agent_flow, data)["instructions"] = 5

    def _set_mode(self, agent_flow, data):
        self._owned_entry(agent_flow, data)["tools"][EntityType.PYTHON_CODE_TOOL][0]["mode"] = 1

    def _set_shared_instructions(self, agent_flow, data):
        for entry in data[EntityType.SURFACE]:
            if entry["id"] == agent_flow["default_surface"].id:
                entry["instructions"] = 5

    def _owned_entry(self, agent_flow, data):
        return next(
            entry
            for entry in data[EntityType.SURFACE]
            if entry["id"] == agent_flow["owned_surface"].id
        )

    @pytest.mark.parametrize("edit", ["_set_instructions", "_set_shared_instructions"])
    def test_numeric_instructions_import_once_then_reuse(
        self, edit, agent_flow, export_file, import_file, default_org
    ):
        data = json.loads(export_file)
        getattr(self, edit)(agent_flow, data)
        hand_edited_file = json.dumps(data)
        agent_state_before = _surface_state(agent_flow["agent"])

        import_file(hand_edited_file)
        counts_after_first_import = _org_counts(default_org)
        import_file(hand_edited_file)

        assert _org_counts(default_org) == counts_after_first_import
        assert Surface.objects.filter(organization=default_org, instructions="5").count() == 1
        assert _surface_state(agent_flow["agent"]) == agent_state_before

    def test_unknown_mode_is_rejected_and_writes_nothing(
        self, agent_flow, export_file, import_file, default_org
    ):
        data = json.loads(export_file)
        self._set_mode(agent_flow, data)
        agent_state_before = _surface_state(agent_flow["agent"])
        counts_before = _org_counts(default_org)
        graphs_before = Graph.objects.count()

        with pytest.raises(ValidationError):
            import_file(json.dumps(data))

        assert _org_counts(default_org) == counts_before
        assert Graph.objects.count() == graphs_before
        assert _surface_state(agent_flow["agent"]) == agent_state_before

    def test_partial_import_is_rejected_and_writes_nothing(self, agent_flow, default_org):
        export_result = GraphPartialExportService(entity_registry).export(
            [NodeRef(entity_type=EntityType.AGENT_NODE, node_id=agent_flow["agent_node"].id)],
            org_id=default_org.id,
        )
        data = json.loads(json.dumps(export_result.data))
        self._set_mode(agent_flow, data)
        target_graph = Graph.objects.create(
            name="target flow", metadata={"nodes": [], "edges": []}, org=default_org
        )
        counts_before = _org_counts(default_org)

        with pytest.raises(ValidationError):
            PartialImportService(entity_registry).import_data(
                data, target_graph, org_id=default_org.id
            )

        assert _org_counts(default_org) == counts_before
        assert not target_graph.agent_node_list.exists()


@pytest.mark.django_db
class TestReusedAgentSurfaceConflicts:
    def test_default_row_on_another_agents_equivalent_surface_does_not_count(
        self, owned_surface_default_flow, export_service, import_file, default_org
    ):
        agent_flow = owned_surface_default_flow
        export_file = json.dumps(
            export_service.export_entities(EntityType.GRAPH, [agent_flow["graph"].id])
        )
        other_agent = AgentDefinition.objects.create(
            organization=default_org, name="other agent"
        )
        owned_surface = agent_flow["owned_surface"]
        other_agents_twin = Surface.objects.create(
            organization=default_org,
            name="other agent's surf",
            instructions=owned_surface.instructions,
            owner_agent=other_agent,
        )
        for row in owned_surface.python_tools.all():
            SurfacePythonTool.objects.create(
                surface=other_agents_twin, python_tool_id=row.python_tool_id, mode=row.mode
            )
        for row in owned_surface.mcp_tools.all():
            SurfaceMcpTool.objects.create(
                surface=other_agents_twin, mcp_tool_id=row.mcp_tool_id, mode=row.mode
            )
        AgentDefaultSurface.objects.filter(
            agent_definition=agent_flow["agent"], surface=owned_surface
        ).update(surface=other_agents_twin)

        id_mapper = import_file(export_file)

        assert id_mapper.get(EntityType.AGENT_DEFINITION, agent_flow["agent"].id) != (
            agent_flow["agent"].id
        )


@pytest.fixture
def owned_surface_default_flow(agent_flow):
    AgentDefaultSurface.objects.create(
        agent_definition=agent_flow["agent"],
        surface=agent_flow["owned_surface"],
        place=SurfacePlace.CHAT,
    )
    return agent_flow
