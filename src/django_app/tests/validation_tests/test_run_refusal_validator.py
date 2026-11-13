"""What crew refuses at run time in a node's templates and state paths, found before a write."""

import pytest

from tables.validators.run_refusal_validator import (
    find_run_refusals_in_export,
    node_run_refusals,
)

# Nothing here queries the ORM, but tests/conftest.py's autouse `heal_builtin_roles`
# does before every database test; without the `db` fixture it would query the
# real dev database instead of the test one.
pytestmark = pytest.mark.django_db

REFUSED_UNDERSCORE_KEY = (
    "Placeholder '{a._b}' is not allowed: '_b' starts with '_'. Rename that variable or key."
)
REFUSED_CONVERSION = (
    "Placeholder '{topic!r}' is not allowed: conversions such as '!r' are not supported. "
    "Write '{topic}'."
)


def _refused_bracket(path: str) -> str:
    return (
        f"Variable path '{path}' is not allowed: a bracket holds either a list index such as "
        "[0] or one variable path such as [variables.index], with no brackets, signs or '|' "
        "inside."
    )


def _refused_leading_bracket(path: str) -> str:
    return (
        f"Variable path '{path}' is not allowed: it must start with a variable name, such as "
        "variables.messages[variables.index], not with a bracket."
    )


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        pytest.param(
            {"instructions": "Use {a._b}"},
            {"instructions": [REFUSED_UNDERSCORE_KEY]},
            id="task-instructions-underscore-key",
        ),
        pytest.param(
            {"instructions": "Say {topic!r}"},
            {"instructions": [REFUSED_CONVERSION]},
            id="task-instructions-conversion",
        ),
        pytest.param(
            {"instructions": "{a._b} and again {a._b}"},
            {"instructions": [REFUSED_UNDERSCORE_KEY]},
            id="one-message-per-distinct-placeholder",
        ),
        pytest.param(
            {"query": "Find {topic!r}"},
            {"query": [REFUSED_CONVERSION]},
            id="knowledge-query",
        ),
        pytest.param(
            {"input_map": {"first": "variables._first", "second": "variables.ok._second"}},
            {
                "input_map": [
                    "Variable path 'variables._first' is not allowed: "
                    "path segments cannot start with '_'.",
                    "Variable path 'variables.ok._second' is not allowed: "
                    "path segments cannot start with '_'.",
                ]
            },
            id="input-map-every-refused-value",
        ),
        pytest.param(
            {"input_map": {"user": "variables._user|guest"}},
            {
                "input_map": [
                    "Variable path 'variables._user' is not allowed: "
                    "path segments cannot start with '_'."
                ]
            },
            id="input-map-names-the-path-without-its-default",
        ),
        pytest.param(
            {"input_map": {"blank": "", "default_only": "|null", "user": "variables.user"}},
            {
                "input_map": [
                    "Input map entry 'blank' has no variable path.",
                    "Input map entry 'default_only' has no variable path.",
                ]
            },
            id="input-map-entry-without-a-path",
        ),
        pytest.param(
            {"output_variable_path": "variables.result|_x"},
            {
                "output_variable_path": [
                    "Variable path 'variables.result|_x' is not allowed: "
                    "path segments cannot start with '_'."
                ]
            },
            id="output-path-is-read-whole",
        ),
        pytest.param(
            {"output_map": {"context": "variables.__class__"}},
            {
                "output_map": [
                    "Variable path 'variables.__class__' is not allowed: "
                    "path segments cannot start with '_'."
                ]
            },
            id="end-node-output-map",
        ),
        pytest.param(
            {
                "pre_output_variable_path": "variables._pre",
                "post_output_variable_path": "variables.items[0]._post",
            },
            {
                "pre_output_variable_path": [
                    "Variable path 'variables._pre' is not allowed: "
                    "path segments cannot start with '_'."
                ],
                "post_output_variable_path": [
                    "Variable path 'variables.items[0]._post' is not allowed: "
                    "path segments cannot start with '_'."
                ],
            },
            id="classification-table-output-paths",
        ),
        pytest.param(
            {
                "pre_input_map": {"x": "variables._x|null"},
                "post_input_map": {"x": "variables.messages[variables._index]"},
                "prompt_configs": [
                    {"kind": "system_one", "prompt_text": "{x!r}", "input_map": {"x": "_x"}},
                    {"kind": "llm", "input_map": {"x": "variables.x"}},
                ],
            },
            {
                "pre_input_map": [
                    "Variable path 'variables._x' is not allowed: "
                    "path segments cannot start with '_'."
                ],
                "post_input_map": [
                    "Variable path 'variables.messages[variables._index]' is not allowed: "
                    "path segments cannot start with '_'."
                ],
                "prompt_configs": [
                    {
                        "input_map": [
                            "Variable path '_x' is not allowed: "
                            "path segments cannot start with '_'."
                        ]
                    },
                    {},
                ],
            },
            id="classification-table-input-maps",
        ),
        pytest.param(
            {
                "pre_input_map": {"blank": "", "default_only": "|null"},
                "prompt_configs": [{"kind": "system_one", "input_map": {"company": ""}}],
            },
            {
                "pre_input_map": [
                    "Input map entry 'blank' has no variable path.",
                    "Input map entry 'default_only' has no variable path.",
                ],
                "prompt_configs": [
                    {"input_map": ["Input map entry 'company' has no variable path."]}
                ],
            },
            id="classification-table-input-map-without-a-path",
        ),
        pytest.param(
            {
                "post_input_map": {
                    "nested": "variables.m[variables.a[variables.b]]",
                    "index_in_key": "variables.m[variables.ids[0]]",
                    "negative": "variables.m[-1]",
                    "default_in_bracket": "variables.m[variables.i|0]",
                }
            },
            {
                "post_input_map": [
                    _refused_bracket("variables.m[variables.a[variables.b]]"),
                    _refused_bracket("variables.m[variables.ids[0]]"),
                    _refused_bracket("variables.m[-1]"),
                    _refused_bracket("variables.m[variables.i"),
                ]
            },
            id="classification-table-input-map-unsupported-brackets",
        ),
        pytest.param(
            {
                "pre_input_map": {"leading": "[variables.k]|null"},
                "prompt_configs": [
                    {"kind": "system_one", "input_map": {"dotted": ".[variables.k]"}}
                ],
            },
            {
                "pre_input_map": [_refused_leading_bracket("[variables.k]")],
                "prompt_configs": [{"input_map": [_refused_leading_bracket(".[variables.k]")]}],
            },
            id="classification-table-input-map-starting-with-a-bracket",
        ),
        pytest.param(
            {"tasks": [{"instructions": "Fine {topic}"}, {"instructions": "Use {a._b}"}]},
            {"tasks": [{}, {"instructions": [REFUSED_UNDERSCORE_KEY]}]},
            id="agent-tasks-aligned-with-sent-rows",
        ),
        pytest.param(
            {"prompt_configs": [{"prompt_text": "{topic!r}"}, {"prompt_text": "{topic}"}]},
            {"prompt_configs": [{"prompt_text": [REFUSED_CONVERSION]}, {}]},
            id="classification-prompts-aligned-with-sent-rows",
        ),
        pytest.param(
            {"fields": [{"variable_path": "variables.chat"}, {"variable_path": "variables._chat"}]},
            {
                "fields": [
                    {},
                    {
                        "variable_path": [
                            "Variable path 'variables._chat' is not allowed: "
                            "path segments cannot start with '_'."
                        ]
                    },
                ]
            },
            id="telegram-fields-aligned-with-sent-rows",
        ),
    ],
)
def test_a_refused_template_or_path_is_reported_on_its_field(node, expected):
    assert node_run_refusals(node) == expected


@pytest.mark.parametrize(
    "node",
    [
        # A plain name is an exact-key lookup, never an attribute walk.
        pytest.param({"instructions": "Hello {_private}"}, id="plain-underscore-name"),
        pytest.param({"instructions": 'Reply as JSON: {"answer": 1}'}, id="json-example"),
        pytest.param({"instructions": "{context[user_input]}"}, id="item-path"),
        pytest.param({"instructions": "{} {0} {topic:>10}"}, id="positional-and-format-spec"),
        pytest.param({"instructions": "Unclosed {a._b"}, id="template-that-does-not-parse"),
        pytest.param(
            {"input_map": {"user": "variables.user|_guest"}}, id="underscore-only-in-the-default"
        ),
        pytest.param(
            {"input_map": {"user": "variables.users[0].name"}, "output_variable_path": "variables"},
            id="valid-paths",
        ),
        pytest.param(
            {
                "pre_input_map": {
                    "text": "variables.messages[variables.index].text|_none",
                    "session": "session_id",
                },
                "post_input_map": {"node": "system_variables.nodes[node_name].result_node"},
                "prompt_configs": [{"kind": "system_one", "input_map": {"x": "variables.x|null"}}],
            },
            id="classification-table-input-maps-with-dynamic-keys",
        ),
        # Crew receives a System One prompt with an empty prompt_text.
        pytest.param(
            {"prompt_configs": [{"kind": "system_one", "prompt_text": "{x!r}"}]},
            id="system-one-prompt-text",
        ),
        # Crew reads a prompt's input map only for System One, and the editor cannot clear it.
        pytest.param(
            {
                "prompt_configs": [
                    {"kind": "llm", "prompt_text": "Rate {x}", "input_map": {"x": "variables._x"}},
                    {"prompt_text": "Rate {x}", "input_map": {"x": ""}},
                ]
            },
            id="llm-prompt-input-map",
        ),
        # Not decided yet for the output map, although crew fails the end node on it.
        pytest.param({"output_map": {"context": ""}}, id="end-node-output-map-without-a-path"),
        # A regular node's input map keeps its own rule; only a classification table's
        # refuses dynamic key brackets.
        pytest.param(
            {"input_map": {"x": "variables.m[variables.i]"}},
            id="regular-input-map-brackets",
        ),
        pytest.param(
            {
                "instructions": None,
                "query": 5,
                "input_map": "__all__",
                "output_map": {"context": 1},
                "output_variable_path": None,
                "tasks": [None, "text", {"instructions": ["{a._b}"]}],
                "prompt_configs": {"prompt_text": "{a._b}"},
                "fields": "variables._x",
            },
            id="values-of-another-type",
        ),
    ],
)
def test_what_crew_runs_is_not_reported(node):
    assert node_run_refusals(node) == {}


def test_an_export_names_flow_node_and_field_of_each_refusal():
    export_data = {
        "Flow": [
            {
                "name": "Main",
                "nodes": [
                    {"node_type": "TaskNode", "node_name": "Writer", "instructions": "{a._b}"},
                    {
                        "node_type": "AgentNode",
                        "node_name": "Helper",
                        "tasks": [{"instructions": "ok"}, {"instructions": "{topic!r}"}],
                    },
                    {"node_type": "EndNode", "output_map": {"context": "variables._x"}},
                ],
            },
            {"name": "Clean", "nodes": [{"node_type": "TaskNode", "instructions": "{topic}"}]},
        ],
        "TaskNode": [{"node_type": "TaskNode", "node_name": "Loose", "query": "{a._b}"}],
    }

    assert find_run_refusals_in_export(export_data) == [
        f"Node 'Writer' of flow 'Main', field 'instructions': {REFUSED_UNDERSCORE_KEY}",
        f"Node 'Helper' of flow 'Main', field 'tasks[1].instructions': {REFUSED_CONVERSION}",
        "Node 'EndNode' of flow 'Main', field 'output_map': Variable path 'variables._x' "
        "is not allowed: path segments cannot start with '_'.",
        f"Node 'Loose', field 'query': {REFUSED_UNDERSCORE_KEY}",
    ]


@pytest.mark.parametrize(
    "export_data",
    [
        pytest.param({}, id="empty"),
        pytest.param({"Flow": ["not a flow", {"name": "No nodes"}]}, id="flow-of-another-type"),
        pytest.param({"Flow": [{"name": "F", "nodes": "x"}], "TaskNode": {}}, id="nodes-not-a-list"),
        pytest.param({"Flow": [{"name": "F", "nodes": [None, 3]}]}, id="node-of-another-type"),
    ],
)
def test_an_export_without_refusals_or_of_an_unexpected_shape_reports_nothing(export_data):
    assert find_run_refusals_in_export(export_data) == []
