"""
The boundary step both import services run (prepare_import_data).
"""

import json

import pytest
from loguru import logger
from rest_framework.exceptions import ValidationError

from tests.fixtures import *  # noqa: F401,F403

from tables.import_export.constants import OWNED_SURFACE_ENTRIES_KEY
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

    def test_default_on_another_agents_surface_missing_from_the_file_is_left_to_the_importer(
        self,
    ):
        # No Surface entry to copy: the importer drops the row like any unmapped surface id.
        prepared = prepare_import_data(
            {
                EntityType.SURFACE: [],
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

        borrower = _agent_entry(prepared, 11)
        assert borrower["default_surfaces"] == [{"surface_id": 1, "place": "flow"}]
        assert _owned_entry_summary(borrower) == []


def _borrowing_bundle():
    """The shape release 1.3.2 left behind: agent 9, a renamed copy of agent 2,
    and the nodes running it point at surfaces 2 and 3, which agent 2 owns."""
    return {
        EntityType.SURFACE: [
            _surface(id=2, name="Philosopher"),
            _surface(id=3, name="banana"),
            _surface(id=4, name="shared"),
        ],
        EntityType.AGENT_DEFINITION: [
            _agent(
                id=2,
                name="Philosopher",
                owned_surfaces=[2, 3],
                default_surfaces=[
                    {"surface_id": 2, "place": "flow"},
                    {"surface_id": 3, "place": "realtime"},
                ],
            ),
            _agent(
                id=9,
                name="Philosopher #2",
                owned_surfaces=[],
                default_surfaces=[
                    {"surface_id": 2, "place": "flow"},
                    {"surface_id": 3, "place": "realtime"},
                    {"surface_id": 4, "place": "all"},
                ],
            ),
        ],
        EntityType.GRAPH: [
            {
                "id": 10,
                "name": "Every Node Gang #4",
                "nodes": [
                    {
                        "node_type": "AgentNode",
                        "id": 102,
                        "agent_definition": 9,
                        "surface_list": [2, 4],
                    },
                    {
                        "node_type": "TaskNode",
                        "id": 103,
                        "agent_definition": 9,
                        "surface_list": [2],
                    },
                    {
                        "node_type": "AgentNode",
                        "id": 104,
                        "agent_definition": 2,
                        "surface_list": [2],
                    },
                    {"node_type": "PythonNode", "id": 105, "surface_list": [2]},
                ],
            }
        ],
    }


def _agent_entry(prepared, agent_id):
    return next(entry for entry in prepared[EntityType.AGENT_DEFINITION] if entry["id"] == agent_id)


def _owned_entry_summary(agent_entry):
    return [(entry["id"], entry["name"]) for entry in agent_entry[OWNED_SURFACE_ENTRIES_KEY]]


def _surface_lists(prepared):
    return {node["id"]: node["surface_list"] for node in prepared[EntityType.GRAPH][0]["nodes"]}


def _copy_ids(prepared, agent_id=9):
    """The borrower's copies by the name of the surface they copy."""
    return {
        entry["name"]: entry["id"]
        for entry in _agent_entry(prepared, agent_id)[OWNED_SURFACE_ENTRIES_KEY]
    }


_BUNDLE_SURFACE_IDS = {2, 3, 4}


class TestBorrowedOwnedSurfaces:
    def test_borrower_gets_its_own_copy_of_each_borrowed_surface(self):
        prepared = prepare_import_data(_borrowing_bundle())

        borrower = _agent_entry(prepared, 9)
        copy_ids = _copy_ids(prepared)
        assert set(copy_ids) == {"Philosopher", "banana"}
        assert not set(copy_ids.values()) & _BUNDLE_SURFACE_IDS
        assert borrower["owned_surfaces"] == [copy_ids["Philosopher"], copy_ids["banana"]]
        assert borrower["default_surfaces"] == [
            {"surface_id": copy_ids["Philosopher"], "place": "flow"},
            {"surface_id": copy_ids["banana"], "place": "realtime"},
            {"surface_id": 4, "place": "all"},
        ]
        copy_entry = borrower[OWNED_SURFACE_ENTRIES_KEY][0]
        assert copy_entry == {**_surface(id=2, name="Philosopher"), "id": copy_ids["Philosopher"]}

    def test_nodes_running_the_borrower_use_its_copy(self):
        prepared = prepare_import_data(_borrowing_bundle())

        # One copy per (agent, surface): both nodes and the default row share it.
        # The owner's node and a node of a type without agents are untouched.
        copy_id = _copy_ids(prepared)["Philosopher"]
        assert _surface_lists(prepared) == {102: [copy_id, 4], 103: [copy_id], 104: [2], 105: [2]}

    def test_owner_and_shared_surfaces_are_untouched(self):
        prepared = prepare_import_data(_borrowing_bundle())

        owner = _agent_entry(prepared, 2)
        assert owner["owned_surfaces"] == [2, 3]
        assert _owned_entry_summary(owner) == [(2, "Philosopher"), (3, "banana")]
        assert owner["default_surfaces"] == [
            {"surface_id": 2, "place": "flow"},
            {"surface_id": 3, "place": "realtime"},
        ]
        assert [entry["id"] for entry in prepared[EntityType.SURFACE]] == [4]

    def test_borrow_by_a_node_only_is_repaired(self):
        bundle = _borrowing_bundle()
        _agent_entry(bundle, 9)["default_surfaces"] = []

        prepared = prepare_import_data(bundle)

        copy_ids = _copy_ids(prepared)
        assert list(copy_ids) == ["Philosopher"]
        assert _surface_lists(prepared)[102] == [copy_ids["Philosopher"], 4]

    def test_partial_bundle_nodes_are_repointed(self):
        bundle = _borrowing_bundle()
        nodes = bundle.pop(EntityType.GRAPH)[0]["nodes"]
        bundle[EntityType.AGENT_NODE] = [nodes[0]]
        bundle[EntityType.TASK_NODE] = [nodes[1]]

        prepared = prepare_import_data(bundle)

        copy_id = _copy_ids(prepared)["Philosopher"]
        assert prepared[EntityType.AGENT_NODE][0]["surface_list"] == [copy_id, 4]
        assert prepared[EntityType.TASK_NODE][0]["surface_list"] == [copy_id]

    def test_copy_id_skips_every_surface_id_the_file_references(self):
        bundle = _borrowing_bundle()
        # 40 and 41 have no Surface entry; a copy under either id would be wired to
        # that node, including one whose agent was deleted.
        nodes = bundle[EntityType.GRAPH][0]["nodes"]
        nodes[2]["surface_list"] = [2, 40]
        nodes.append(
            {"node_type": "AgentNode", "id": 106, "agent_definition": None, "surface_list": [41]}
        )

        prepared = prepare_import_data(bundle)

        assert not set(_copy_ids(prepared).values()) & {*_BUNDLE_SURFACE_IDS, 40, 41}

    def test_one_warning_per_borrowed_surface(self):
        messages = []
        handler_id = logger.add(messages.append, level="WARNING", format="{message}")
        try:
            prepare_import_data(_borrowing_bundle())
        finally:
            logger.remove(handler_id)

        assert len(messages) == 2

    def test_input_is_not_modified(self):
        bundle = _borrowing_bundle()

        prepare_import_data(bundle)

        assert bundle == _borrowing_bundle()

    def test_clean_bundle_gets_no_copies(self):
        bundle = _borrowing_bundle()
        borrower = _agent_entry(bundle, 9)
        borrower["default_surfaces"] = [{"surface_id": 4, "place": "all"}]
        for node in bundle[EntityType.GRAPH][0]["nodes"][:2]:
            node["agent_definition"] = 2

        prepared = prepare_import_data(bundle)

        assert _owned_entry_summary(_agent_entry(prepared, 9)) == []
        assert _surface_lists(prepared) == {102: [2, 4], 103: [2], 104: [2], 105: [2]}
        assert [entry["id"] for entry in prepared[EntityType.SURFACE]] == [4]

    @pytest.mark.parametrize(
        "node",
        [
            {"node_type": "AgentNode", "id": 106, "agent_definition": None, "surface_list": [2]},
            {"node_type": "AgentNode", "id": 106, "agent_definition": "9", "surface_list": [2]},
            {"node_type": "AgentNode", "id": 106, "agent_definition": [9], "surface_list": [2]},
            {"node_type": "AgentNode", "id": 106, "agent_definition": 77, "surface_list": [2]},
            {"node_type": "TaskNode", "id": 106, "agent_definition": 9, "surface_list": "2"},
            {"node_type": "TaskNode", "id": 106, "agent_definition": 9, "surface_list": [[2]]},
            "not an object",
        ],
    )
    def test_node_without_a_borrowing_agent_is_left_alone(self, node):
        bundle = _borrowing_bundle()
        _agent_entry(bundle, 9)["default_surfaces"] = []
        bundle[EntityType.GRAPH][0]["nodes"] = [node]

        prepared = prepare_import_data(bundle)

        assert prepared[EntityType.GRAPH][0]["nodes"] == [node]
        assert _owned_entry_summary(_agent_entry(prepared, 9)) == []


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
                    _mcp_tool(id=10, timeout="30"),
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
            _python_code(venv="not-an-int"),
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
            {"transport": "not a url"},
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
