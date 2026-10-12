"""
AgentDefinitionStrategy.find_existing reuses an agent only when its owned
surfaces equal the file's by content, and then maps every exported owned
surface to one of the agent's.
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
            name="matching py",
            description="description",
            python_code=PythonCode.objects.create(code="x", entrypoint="main", libraries=""),
        ),
        "mcp": McpTool.objects.create(
            org=default_org, name="matching mcp", transport="https://example.com", tool_name="t"
        ),
    }


def _owned_surface(agent, name, instructions="", python=(), mcp=()):
    surface = Surface.objects.create(
        org=agent.org, name=name, instructions=instructions, owner_agent=agent
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
def test_agent_reused_exactly_when_owned_surfaces_match(
    build_case, expected_match, tools, export_service, default_org
):
    agent = AgentDefinition.objects.create(org=default_org, name="matching agent")
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

    assert (found == agent) is expected_match
    if expected_match:
        pairing = strategy._match_surfaces(found, *strategy._entry_surfaces(entry, id_mapper))
        assert set(pairing) == {owned["id"] for owned in entry[OWNED_SURFACE_ENTRIES_KEY]}
        assert set(pairing.values()) == set(agent.owned_surfaces.values_list("id", flat=True))
