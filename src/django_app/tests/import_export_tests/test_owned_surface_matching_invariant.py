"""
The SQL reuse filter of AgentDefinitionStrategy.find_existing and the Python
pairing import_entity uses to map a reused agent's owned surfaces must agree:
find_existing returns the agent exactly when the pairing succeeds. A
disagreement either loses the owned surfaces of a reused agent or turns a reuse
into a 409.
"""

import pytest
from django.utils import timezone

from tests.fixtures import *  # noqa: F401,F403

from agents.models import AgentDefinition, Surface, SurfaceMcpTool, SurfacePythonTool, ToolMode
from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.import_export.utils import nest_owned_surface_entries
from tables.models import McpTool, PythonCode, PythonCodeTool


@pytest.fixture
def tools(default_org):
    return {
        "python": PythonCodeTool.objects.create(
            org=default_org,
            name="invariant py",
            description="description",
            python_code=PythonCode.objects.create(code="x", entrypoint="main", libraries=""),
        ),
        "mcp": McpTool.objects.create(
            org=default_org, name="invariant mcp", transport="https://example.com", tool_name="t"
        ),
    }


def _owned_surface(agent, name, instructions="", python=(), mcp=()):
    surface = Surface.objects.create(
        organization=agent.organization, name=name, instructions=instructions, owner_agent=agent
    )
    for python_tool, mode in python:
        SurfacePythonTool.objects.create(surface=surface, python_tool=python_tool, mode=mode)
    for mcp_tool, mode in mcp:
        SurfaceMcpTool.objects.create(surface=surface, mcp_tool=mcp_tool, mode=mode)
    return surface


def _owned_entry(entry, name):
    return next(
        owned for owned in entry[OWNED_SURFACE_ENTRIES_KEY] if owned["name"] == name
    )


def _unchanged(agent, tools):
    _owned_surface(agent, "a", "k")


def _renamed(agent, tools):
    surface = _owned_surface(agent, "a", "k")
    yield
    surface.name = "renamed"
    surface.save(update_fields=["name"])


def _twins(agent, tools):
    _owned_surface(agent, "a", "twin", python=[(tools["python"], ToolMode.ALLOW)])
    _owned_surface(agent, "a #2", "twin", python=[(tools["python"], ToolMode.ALLOW)])


def _twin_edited(agent, tools):
    _owned_surface(agent, "a", "twin")
    twin = _owned_surface(agent, "a #2", "twin")
    yield
    twin.instructions = "edited"
    twin.save(update_fields=["instructions"])


def _other_multiplicity_in_one_content(agent, tools):
    _owned_surface(agent, "a", "k")
    _owned_surface(agent, "b", "k")
    _owned_surface(agent, "c", "other")
    entry = yield
    _owned_entry(entry, "c")["instructions"] = "k"


def _extra_surface_owned_after_export(agent, tools):
    _owned_surface(agent, "a", "k")
    yield
    _owned_surface(agent, "added later", "k")


def _unmapped_tool_in_file(agent, tools):
    _owned_surface(agent, "a", "k")
    entry = yield
    _owned_entry(entry, "a")["tools"][EntityType.PYTHON_CODE_TOOL].append(
        {"python_tool_id": 999999, "mode": ToolMode.ALLOW}
    )


def _soft_deleted_tool_row(agent, tools):
    surface = _owned_surface(agent, "a", "k", python=[(tools["python"], ToolMode.DENY)])
    entry = yield
    SurfacePythonTool.all_objects.filter(surface=surface).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )
    _owned_entry(entry, "a")["tools"][EntityType.PYTHON_CODE_TOOL] = []


def _soft_deleted_tool_row_still_in_file(agent, tools):
    surface = _owned_surface(agent, "a", "k", python=[(tools["python"], ToolMode.DENY)])
    yield
    SurfacePythonTool.all_objects.filter(surface=surface).update(
        is_soft_deleted=True, soft_deleted_at=timezone.now()
    )


def _mcp_tool(agent, tools):
    _owned_surface(agent, "a", "k", mcp=[(tools["mcp"], ToolMode.ALLOW)])


def _mcp_mode_changed(agent, tools):
    surface = _owned_surface(agent, "a", "k", mcp=[(tools["mcp"], ToolMode.ALLOW)])
    yield
    SurfaceMcpTool.objects.filter(surface=surface).update(mode=ToolMode.DENY)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "build_case, expected_match",
    [
        (_unchanged, True),
        (_renamed, True),
        (_twins, True),
        (_twin_edited, False),
        (_other_multiplicity_in_one_content, False),
        (_extra_surface_owned_after_export, False),
        (_unmapped_tool_in_file, True),
        (_soft_deleted_tool_row, True),
        (_soft_deleted_tool_row_still_in_file, False),
        (_mcp_tool, True),
        (_mcp_mode_changed, False),
    ],
    ids=lambda value: value.__name__.strip("_") if callable(value) else str(value),
)
def test_sql_match_agrees_with_python_pairing(
    build_case, expected_match, tools, export_service, default_org
):
    agent = AgentDefinition.objects.create(organization=default_org, name="invariant agent")
    case = build_case(agent, tools)
    if case is not None:
        next(case)

    export_data = export_service.export_entities(EntityType.AGENT_DEFINITION, [agent.id])
    entry = nest_owned_surface_entries(export_data)[EntityType.AGENT_DEFINITION][0]
    id_mapper = IDMapper()
    for entity_type in (EntityType.PYTHON_CODE_TOOL, EntityType.MCP_TOOL):
        for tool_entry in export_data.get(entity_type, []):
            id_mapper.map(entity_type, tool_entry["id"], tool_entry["id"], was_created=False)

    if case is not None:
        try:
            case.send(entry)
        except StopIteration:
            pass

    strategy = entity_registry.get_strategy(EntityType.AGENT_DEFINITION)
    found = strategy.find_existing(entry, id_mapper, org_id=default_org.id)
    pairing = strategy._pair_owned_surfaces(entry, id_mapper, agent.id)

    assert (found == agent) is expected_match
    assert (pairing is not None) is expected_match
