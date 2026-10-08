"""
The boundary step both import services run (prepare_import_data).
"""

import json

import pytest
from rest_framework.exceptions import ValidationError

from tests.fixtures import *  # noqa: F401,F403

from tables.import_export.enums import EntityType
from tables.import_export.preparation import prepare_import_data
from tables.models import McpTool, PythonCodeTool


def _surface(**overrides):
    return {
        "id": 1,
        "name": "surf",
        "instructions": "text",
        "tools": {
            EntityType.PYTHON_CODE_TOOL: [{"python_tool_id": 7, "mode": "allow"}],
            EntityType.MCP_TOOL: [{"mcp_tool_id": 8, "mode": "deny"}],
        },
        **overrides,
    }


def _python_tool(**overrides):
    return {
        "id": 7,
        "name": "py",
        "description": "description",
        "variables": [],
        "use_storage": False,
        "built_in": False,
        "python_code": {
            "code": "def main(): return 1",
            "libraries": "",
            "entrypoint": "main",
            "global_kwargs": {},
        },
        "labels": [],
        **overrides,
    }


def _python_code(**overrides):
    return _python_tool(python_code={**_python_tool()["python_code"], **overrides})


def _mcp_tool(**overrides):
    return {
        "id": 8,
        "name": "mcp",
        "transport": "https://example.com/mcp",
        "tool_name": "search",
        "timeout": 30.0,
        "init_timeout": 10,
        "labels": [],
        **overrides,
    }


def _agent(**overrides):
    return {
        "id": 10,
        "name": "agent",
        "owned_surfaces": [1],
        "default_surfaces": [{"surface_id": 1, "place": "chat"}],
        **overrides,
    }


class TestSurfaceEntries:
    def test_well_formed_entry_and_missing_instructions_pass(self):
        entry_without_instructions = _surface()
        del entry_without_instructions["instructions"]

        prepare_import_data(
            {
                EntityType.SURFACE: [
                    _surface(),
                    entry_without_instructions,
                    _surface(id=3, name="numeric", instructions=5),
                ]
            }
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"instructions": None},
            {"instructions": True},
            {"tools": []},
            {"tools": {EntityType.PYTHON_CODE_TOOL: {}}},
            {"tools": {EntityType.PYTHON_CODE_TOOL: [{"python_tool_id": 7, "mode": 1}]}},
            {"tools": {EntityType.MCP_TOOL: [{"mcp_tool_id": "8", "mode": "allow"}]}},
            {"tools": {EntityType.MCP_TOOL: [{"mcp_tool_id": True, "mode": "allow"}]}},
            {"tools": {EntityType.MCP_TOOL: [{"mode": "allow"}]}},
            {"tools": {EntityType.MCP_TOOL: ["not an object"]}},
            {"tools": {EntityType.MCP_TOOL: [{"mcp_tool_id": 8, "mode": "ALLOW"}]}},
            {"tools": {EntityType.MCP_TOOL: [{"mcp_tool_id": 8, "mode": "sometimes"}]}},
            {
                "tools": {
                    EntityType.PYTHON_CODE_TOOL: [
                        {"python_tool_id": 7, "mode": "allow"},
                        {"python_tool_id": 7, "mode": "deny"},
                    ]
                }
            },
        ],
    )
    def test_malformed_entry_is_rejected(self, overrides):
        with pytest.raises(ValidationError):
            prepare_import_data({EntityType.SURFACE: [_surface(**overrides)]})

    def test_non_object_entry_is_rejected(self):
        with pytest.raises(ValidationError):
            prepare_import_data({EntityType.SURFACE: ["not an object"]})

    @pytest.mark.parametrize("entry_id", [None, "1", True])
    def test_entry_without_integer_id_is_rejected(self, entry_id):
        with pytest.raises(ValidationError):
            prepare_import_data({EntityType.SURFACE: [_surface(id=entry_id)]})


class TestAgentEntries:
    def test_own_and_shared_default_surfaces_pass(self):
        prepare_import_data(
            {
                EntityType.SURFACE: [_surface(), _surface(id=2, name="shared")],
                EntityType.AGENT_DEFINITION: [
                    _agent(
                        default_surfaces=[
                            {"surface_id": 1, "place": "chat"},
                            {"surface_id": 2, "place": "flow"},
                        ]
                    ),
                    _agent(id=11, owned_surfaces=[], default_surfaces=[]),
                ],
            }
        )

    @pytest.mark.parametrize(
        "entry",
        [
            "not an object",
            _agent(id=None),
            _agent(id="10"),
            _agent(id=True),
            _agent(owned_surfaces=None),
            _agent(owned_surfaces="1"),
            _agent(owned_surfaces=["1"]),
            _agent(owned_surfaces=[True]),
            _agent(default_surfaces=None),
            _agent(default_surfaces=["not an object"]),
            _agent(default_surfaces=[{"surface_id": "1", "place": "chat"}]),
            _agent(default_surfaces=[{"surface_id": True, "place": "chat"}]),
            _agent(default_surfaces=[{"surface_id": 1, "place": "everywhere"}]),
            _agent(default_surfaces=[{"surface_id": 1}]),
            _agent(llm_config="7"),
            _agent(fcm_llm_config=[7]),
            _agent(max_iter="many"),
        ],
    )
    def test_malformed_entry_is_rejected(self, entry):
        with pytest.raises(ValidationError):
            prepare_import_data(
                {EntityType.SURFACE: [_surface()], EntityType.AGENT_DEFINITION: [entry]}
            )

    def test_default_on_a_surface_another_agent_owns_is_rejected(self):
        # The agents API rejects this state; the import must not create it.
        with pytest.raises(ValidationError) as exc:
            prepare_import_data(
                {
                    EntityType.SURFACE: [_surface()],
                    EntityType.AGENT_DEFINITION: [
                        _agent(default_surfaces=[]),
                        _agent(
                            id=11,
                            owned_surfaces=[],
                            default_surfaces=[{"surface_id": 1, "place": "flow"}],
                        ),
                    ],
                }
            )

        assert "owned by AgentDefinition 10" in str(exc.value.detail)


class TestToolEntries:
    def test_well_formed_and_legacy_entries_pass(self):
        legacy_python_tool = _python_tool(
            created_at="2020-01-01T00:00:00Z",
            updated_at="2020-01-02T00:00:00Z",
            is_soft_deleted=False,
            soft_deleted_at=None,
        )
        del legacy_python_tool["use_storage"]
        del legacy_python_tool["python_code"]["entrypoint"]
        del legacy_python_tool["python_code"]["global_kwargs"]

        prepare_import_data(
            {
                EntityType.PYTHON_CODE_TOOL: [
                    _python_tool(),
                    legacy_python_tool,
                    _python_tool(id=70, name=5, description=5, use_storage="yes"),
                    _python_code(code=5, entrypoint=5),
                ],
                EntityType.MCP_TOOL: [
                    _mcp_tool(),
                    _mcp_tool(id=9, init_timeout=10.5),
                    _mcp_tool(id=10, timeout="30", transport=5),
                ],
            }
        )

    @pytest.mark.parametrize(
        "entry",
        [
            _python_tool(id=None),
            _python_tool(name=None),
            _python_tool(name=""),
            _python_tool(description=True),
            _python_tool(use_storage="sometimes"),
            _python_tool(variables=None),
            _python_tool(python_code=None),
            _python_tool(python_code="def main(): pass"),
            _python_code(code=None),
            _python_code(libraries=None),
            _python_code(libraries="git+https://example.com/repo.git"),
            _python_code(global_kwargs=None),
            "not an object",
        ],
    )
    def test_malformed_python_tool_is_rejected(self, entry):
        with pytest.raises(ValidationError):
            prepare_import_data({EntityType.PYTHON_CODE_TOOL: [entry]})

    def test_python_code_without_code_is_rejected(self):
        entry = _python_tool()
        del entry["python_code"]["code"]

        with pytest.raises(ValidationError):
            prepare_import_data({EntityType.PYTHON_CODE_TOOL: [entry]})

    @pytest.mark.parametrize(
        "overrides",
        [
            {"timeout": "abc"},
            {"init_timeout": None},
            {"transport": ""},
            {"tool_name": None},
            {"id": "8"},
        ],
    )
    def test_malformed_mcp_tool_is_rejected(self, overrides):
        with pytest.raises(ValidationError):
            prepare_import_data({EntityType.MCP_TOOL: [_mcp_tool(**overrides)]})

    def test_every_bad_entry_is_listed(self):
        with pytest.raises(ValidationError) as exc:
            prepare_import_data(
                {
                    EntityType.PYTHON_CODE_TOOL: [_python_tool(description=True)],
                    EntityType.MCP_TOOL: [_mcp_tool(timeout="abc")],
                    EntityType.SURFACE: [_surface(instructions=None)],
                }
            )

        assert len(exc.value.detail["detail"]) == 3


@pytest.mark.django_db
def test_malformed_tool_file_writes_nothing(import_service, default_org):
    tools_before = (PythonCodeTool.objects.count(), McpTool.objects.count())
    data = {
        EntityType.PYTHON_CODE_TOOL: [_python_tool()],
        EntityType.MCP_TOOL: [_mcp_tool(timeout="abc")],
    }

    with pytest.raises(ValidationError):
        import_service.import_data(json.loads(json.dumps(data)), EntityType.GRAPH)

    assert (PythonCodeTool.objects.count(), McpTool.objects.count()) == tools_before
