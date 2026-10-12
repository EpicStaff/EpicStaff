"""
The reuse lookups load at most MAX_REUSE_CANDIDATES candidates per file entry,
however many rows of the same name an organization holds. A match past the bound
is missed and one copy is created; being the newest, the next import reuses it.
"""

from copy import deepcopy

import pytest
from django.db import connection

from tests.fixtures import *  # noqa: F401,F403

from agents.models import AgentDefinition, Surface
from tables.import_export.constants import MAX_REUSE_CANDIDATES, OWNED_SURFACE_ENTRIES_KEY
from tables.import_export.enums import EntityType
from tables.import_export.id_mapper import IDMapper
from tables.import_export.registry import entity_registry
from tables.models import McpTool, PythonCode, PythonCodeTool


SEEDED_ROWS = MAX_REUSE_CANDIDATES + 10


class _RowCount:
    """Counts the rows SELECTs return, via connection.execute_wrapper.

    The active organization lookup done by get_org_scope_q is not a candidate
    row, so it is left out.
    """

    def __init__(self):
        self.rows = 0

    def __call__(self, execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        row_count = context["cursor"].rowcount
        is_select = sql.lstrip().upper().startswith("SELECT")
        is_organization_lookup = 'FROM "rbac_organization"' in sql
        if is_select and not is_organization_lookup and row_count and row_count > 0:
            self.rows += row_count
        return result


def _find_existing(entity_type, entry: dict, id_mapper: IDMapper, org):
    """Return (found row, rows loaded) of one find_existing call."""
    row_count = _RowCount()
    with connection.execute_wrapper(row_count):
        found = entity_registry.get_strategy(entity_type).find_existing(
            entry, id_mapper, org_id=org.id
        )
    return found, row_count.rows


def _family_name(base_name: str, number: int) -> str:
    return base_name if number == 1 else f"{base_name} #{number}"


def _python_code_data(code: str) -> dict:
    return {"code": code, "entrypoint": "main", "libraries": "", "global_kwargs": {}}


def _python_tool_entry(code: str) -> dict:
    return {
        "id": 1,
        "name": "py",
        "description": "description",
        "variables": [],
        "use_storage": False,
        "python_code": _python_code_data(code),
    }


def _seed_python_tools(org, codes: list[str]):
    for number, code in enumerate(codes, start=1):
        PythonCodeTool.objects.create(
            org=org,
            name=_family_name("py", number),
            description="description",
            python_code=PythonCode.objects.create(**_python_code_data(code)),
        )


@pytest.mark.django_db
class TestPythonToolLookupBound:
    def test_loads_at_most_the_bound(self, default_org):
        _seed_python_tools(default_org, [f"return {number}" for number in range(SEEDED_ROWS)])

        found, rows = _find_existing(
            EntityType.PYTHON_CODE_TOOL, _python_tool_entry("not seeded"), IDMapper(), default_org
        )

        assert found is None
        assert rows <= MAX_REUSE_CANDIDATES

    def test_match_within_the_bound_is_reused(self, default_org):
        # Exact name first, then renamed copies newest first.
        codes = [f"return {number}" for number in range(SEEDED_ROWS)]
        _seed_python_tools(default_org, codes)

        for code in (codes[0], codes[-1]):
            found, _ = _find_existing(
                EntityType.PYTHON_CODE_TOOL, _python_tool_entry(code), IDMapper(), default_org
            )
            assert found.python_code.code == code

    def test_match_past_the_bound_is_missed_safely(self, default_org):
        codes = [f"return {number}" for number in range(SEEDED_ROWS)]
        _seed_python_tools(default_org, codes)

        found, _ = _find_existing(
            EntityType.PYTHON_CODE_TOOL, _python_tool_entry(codes[3]), IDMapper(), default_org
        )

        # The import creates a copy instead of reusing a wrong row.
        assert found is None

    def test_reimport_after_a_miss_reuses_the_copy_it_created(self, default_org, import_service):
        codes = [f"return {number}" for number in range(SEEDED_ROWS)]
        _seed_python_tools(default_org, codes)
        bundle = {EntityType.PYTHON_CODE_TOOL: [_python_tool_entry(codes[3])]}
        tools_before = PythonCodeTool.objects.filter(org=default_org).count()

        first_id_mapper, _ = import_service.import_data(deepcopy(bundle), EntityType.GRAPH)
        second_id_mapper, _ = import_service.import_data(deepcopy(bundle), EntityType.GRAPH)

        created_tool_id = first_id_mapper.get(EntityType.PYTHON_CODE_TOOL, 1)
        assert first_id_mapper.was_created(EntityType.PYTHON_CODE_TOOL, 1)
        assert second_id_mapper.get(EntityType.PYTHON_CODE_TOOL, 1) == created_tool_id
        assert PythonCodeTool.objects.filter(org=default_org).count() == tools_before + 1


@pytest.mark.django_db
def test_shared_surface_lookup_loads_at_most_the_bound(default_org):
    Surface.objects.bulk_create(
        [
            Surface(org=default_org, name=_family_name("S", number), instructions="same")
            for number in range(1, SEEDED_ROWS + 1)
        ]
    )
    mcp_tool = McpTool.objects.create(
        org=default_org, name="mcp", transport="https://example.com/mcp", tool_name="t"
    )
    id_mapper = IDMapper()
    id_mapper.map(EntityType.MCP_TOOL, 1, mcp_tool.id, was_created=False)
    entry = {
        "id": 1,
        "name": "S",
        "instructions": "same",
        "tools": {
            EntityType.PYTHON_CODE_TOOL: [],
            EntityType.MCP_TOOL: [{"mcp_tool_id": 1, "mode": "allow"}],
        },
    }

    found, rows = _find_existing(EntityType.SURFACE, entry, id_mapper, default_org)

    assert found is None
    assert rows <= MAX_REUSE_CANDIDATES


@pytest.mark.django_db
def test_agent_lookup_loads_at_most_the_bound(default_org):
    template = AgentDefinition.objects.create(org=default_org, name="template")
    agent_scalars = {
        key: value
        for key, value in entity_registry.get_strategy(EntityType.AGENT_DEFINITION)
        .export_entity(template)
        .items()
        if key not in ("id", "name")
    }
    template.delete()
    for number in range(1, SEEDED_ROWS + 1):
        agent = AgentDefinition.objects.create(org=default_org, name=_family_name("agent", number))
        Surface.objects.create(
            org=default_org,
            name=f"owned {number}",
            instructions="other",
            owner_agent=agent,
        )
    owned_entry = {"id": 2, "name": "owned", "instructions": "wanted", "tools": {}}
    entry = {
        **agent_scalars,
        "id": 1,
        "name": "agent",
        "owned_surfaces": [2],
        "default_surfaces": [],
        OWNED_SURFACE_ENTRIES_KEY: [owned_entry],
    }

    found, rows = _find_existing(EntityType.AGENT_DEFINITION, entry, IDMapper(), default_org)

    # Each candidate loaded brings its one owned surface along.
    assert found is None
    assert rows <= 2 * MAX_REUSE_CANDIDATES


# Tool or default rows on every seeded candidate: far more than any lookup below
# may load, since the entries carry none.
@pytest.mark.django_db
def test_built_in_tool_stored_with_trailing_newline_is_reused(default_org):
    built_in_tool = PythonCodeTool.objects.create(
        name="py",
        description="description",
        built_in=True,
        python_code=PythonCode.objects.create(**_python_code_data("return 1\n")),
    )

    found, _ = _find_existing(
        EntityType.PYTHON_CODE_TOOL, _python_tool_entry("return 1"), IDMapper(), default_org
    )

    assert found == built_in_tool
