"""
Cost guards for the rename-aware reuse lookups: a find_existing call must not
fetch more rows, or issue more queries, as the org holds more rows of the same
name family -- whether seeded beforehand or created earlier in the same file.
"""

import pytest
from django.db import connection

from tests.fixtures import *  # noqa: F401,F403

from agents.models import AgentDefinition, Surface, ToolMode
from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.models import McpTool, PythonCode, PythonCodeTool


class _QueryCost:
    """Counts queries and the rows SELECTs return, via connection.execute_wrapper."""

    def __init__(self):
        self.queries = 0
        self.rows = 0

    def __call__(self, execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        self.queries += 1
        row_count = context["cursor"].rowcount
        if sql.lstrip().upper().startswith("SELECT") and row_count and row_count > 0:
            self.rows += row_count
        return result


def _cost_of(call) -> tuple[int, int]:
    cost = _QueryCost()
    with connection.execute_wrapper(cost):
        call()
    return cost.queries, cost.rows


def _find_existing_cost(entity_type, entry: dict, id_mapper: IDMapper, org) -> tuple[int, int]:
    strategy = entity_registry.get_strategy(entity_type)
    found = []
    cost = _cost_of(lambda: found.append(strategy.find_existing(entry, id_mapper, org_id=org.id)))
    assert found == [None]
    return cost


def _family_name(base_name: str, number: int) -> str:
    return base_name if number == 1 else f"{base_name} #{number}"


def _python_code_data(code: str) -> dict:
    return {"code": code, "entrypoint": "main", "libraries": "", "global_kwargs": {}}


def _python_tool_entry(entry_id: int, name: str, code: str) -> dict:
    return {
        "id": entry_id,
        "name": name,
        "description": "description",
        "variables": [],
        "use_storage": False,
        "python_code": _python_code_data(code),
        "labels": [],
    }


def _seed_python_tools(org, base_name: str, count: int):
    for number in range(1, count + 1):
        PythonCodeTool.objects.create(
            org=org,
            name=_family_name(base_name, number),
            description="description",
            python_code=PythonCode.objects.create(**_python_code_data(f"return {number}")),
        )


def _seed_shared_surfaces(org, base_name: str, count: int):
    Surface.objects.bulk_create(
        [
            Surface(organization=org, name=_family_name(base_name, number), instructions="same")
            for number in range(1, count + 1)
        ]
    )


def _seed_agents_owning_other_surfaces(org, base_name: str, count: int):
    """Agents with the entry's scalars, each owning one surface of other content."""
    for number in range(1, count + 1):
        agent = AgentDefinition.objects.create(
            organization=org, name=_family_name(base_name, number)
        )
        Surface.objects.create(
            organization=org,
            name=f"{base_name} owned {number}",
            instructions=f"other {number}",
            owner_agent=agent,
        )


def _agent_entry(org, entry_id: int, name: str, owned_surface_entries: list[dict]) -> dict:
    """An exported AgentDefinition entry with the scalars a default agent has, so
    seeded default agents differ from it only in their owned surfaces."""
    return {
        **_exported_agent_scalars(org),
        "id": entry_id,
        "name": name,
        "owned_surfaces": [entry["id"] for entry in owned_surface_entries],
        "default_surfaces": [],
        OWNED_SURFACE_ENTRIES_KEY: owned_surface_entries,
    }


def _exported_agent_scalars(org) -> dict:
    template = AgentDefinition.objects.create(organization=org, name="export template")
    exported = entity_registry.get_strategy(EntityType.AGENT_DEFINITION).export_entity(template)
    template.delete()
    return {key: value for key, value in exported.items() if key not in ("id", "name")}


def _surface_entry(entry_id: int, name: str, instructions: str, mcp_tool_ids=()) -> dict:
    return {
        "id": entry_id,
        "name": name,
        "instructions": instructions,
        "tools": {
            EntityType.PYTHON_CODE_TOOL: [],
            EntityType.MCP_TOOL: [
                {"mcp_tool_id": mcp_tool_id, "mode": ToolMode.ALLOW} for mcp_tool_id in mcp_tool_ids
            ],
        },
    }


@pytest.mark.django_db
class TestCostDoesNotGrowWithSeededFamily:
    def test_python_tool(self, default_org):
        def cost(base_name, seeded):
            _seed_python_tools(default_org, base_name, seeded)
            entry = _python_tool_entry(1, base_name, "return 'not seeded'")
            return _find_existing_cost(EntityType.PYTHON_CODE_TOOL, entry, IDMapper(), default_org)

        assert cost("small", 5) == cost("large", 300)

    def test_shared_surface(self, default_org):
        mcp_tool = McpTool.objects.create(
            org=default_org, name="mcp", transport="https://example.com/mcp", tool_name="t"
        )
        id_mapper = IDMapper()
        id_mapper.map(EntityType.MCP_TOOL, 1, mcp_tool.id, was_created=False)

        def cost(base_name, seeded):
            _seed_shared_surfaces(default_org, base_name, seeded)
            entry = _surface_entry(1, base_name, "same", mcp_tool_ids=[1])
            return _find_existing_cost(EntityType.SURFACE, entry, id_mapper, default_org)

        assert cost("small", 5) == cost("large", 300)

    def test_agent_definition(self, default_org):
        def cost(base_name, seeded):
            _seed_agents_owning_other_surfaces(default_org, base_name, seeded)
            entry = _agent_entry(
                default_org, 1, base_name, [_surface_entry(2, f"{base_name} owned", "wanted")]
            )
            return _find_existing_cost(
                EntityType.AGENT_DEFINITION, entry, IDMapper(), default_org
            )

        assert cost("small", 5) == cost("large", 100)


@pytest.fixture
def per_call_cost(monkeypatch):
    """Record the (queries, rows) of every find_existing call of one strategy."""

    def _instrument(entity_type) -> list[tuple[int, int]]:
        strategy = entity_registry.get_strategy(entity_type)
        original_find_existing = strategy.find_existing
        recorded = []

        def find_existing(*args, **kwargs):
            cost = _QueryCost()
            with connection.execute_wrapper(cost):
                result = original_find_existing(*args, **kwargs)
            recorded.append((cost.queries, cost.rows))
            return result

        monkeypatch.setattr(strategy, "find_existing", find_existing)
        return recorded

    return _instrument


@pytest.mark.django_db
class TestCostDoesNotGrowWithEntriesInOneFile:
    """N same-family entries in one file, each new: every lookup after the first
    sees the rows the earlier entries created."""

    def _max_lookup_cost(self, import_service, per_call_cost, entity_type, export_data):
        recorded = per_call_cost(entity_type)
        import_service.import_data(export_data, EntityType.GRAPH)
        return max(recorded)

    def test_python_tools(self, import_service, per_call_cost):
        def max_cost(base_name, count):
            entries = [
                _python_tool_entry(number, _family_name(base_name, number), f"return {number}")
                for number in range(1, count + 1)
            ]
            return self._max_lookup_cost(
                import_service,
                per_call_cost,
                EntityType.PYTHON_CODE_TOOL,
                {EntityType.PYTHON_CODE_TOOL: entries},
            )

        assert max_cost("small", 5) == max_cost("large", 60)

    def test_shared_surfaces(self, import_service, per_call_cost, default_org):
        def max_cost(base_name, count):
            mcp_tools = [
                McpTool.objects.create(
                    org=default_org,
                    name=f"{base_name} mcp {number}",
                    transport="https://example.com/mcp",
                    tool_name="t",
                )
                for number in range(1, count + 1)
            ]
            mcp_entries = [
                {
                    "id": tool.id,
                    "name": tool.name,
                    "transport": tool.transport,
                    "tool_name": tool.tool_name,
                    "timeout": tool.timeout,
                    "init_timeout": tool.init_timeout,
                    "labels": [],
                }
                for tool in mcp_tools
            ]
            surface_entries = [
                _surface_entry(
                    number, _family_name(base_name, number), "same", [mcp_tools[number - 1].id]
                )
                for number in range(1, count + 1)
            ]
            return self._max_lookup_cost(
                import_service,
                per_call_cost,
                EntityType.SURFACE,
                {EntityType.MCP_TOOL: mcp_entries, EntityType.SURFACE: surface_entries},
            )

        assert max_cost("small", 5) == max_cost("large", 60)

    def test_agent_definitions(self, import_service, per_call_cost, default_org):
        def max_cost(base_name, count):
            surface_entries = [
                _surface_entry(1000 + number, f"{base_name} owned", f"distinct {number}")
                for number in range(1, count + 1)
            ]
            agent_entries = [
                {
                    key: value
                    for key, value in _agent_entry(
                        default_org, number, base_name, [surface_entries[number - 1]]
                    ).items()
                    if key != OWNED_SURFACE_ENTRIES_KEY
                }
                for number in range(1, count + 1)
            ]
            return self._max_lookup_cost(
                import_service,
                per_call_cost,
                EntityType.AGENT_DEFINITION,
                {
                    EntityType.SURFACE: surface_entries,
                    EntityType.AGENT_DEFINITION: agent_entries,
                },
            )

        assert max_cost("small", 5) == max_cost("large", 60)
