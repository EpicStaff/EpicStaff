"""
Tests for ClassificationDecisionTableNodeSubgraph.

Sandbox (RunPythonCodeService.run_code) is patched to execute the generated code
in-process so expression/manipulation logic is fully exercised.
LLM calls (litellm.acompletion) are replaced with AsyncMock.

NOTE: The CDT subgraph uses `src.crew.services.run_python_code_service.RunPythonCodeService`
(absolute import). We must patch that exact class, not the bare `services.*` alias.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from dotdict import DotDict
from langgraph.graph import END, StateGraph

from models.state import State
from services.graph.events import StopEvent

# Import via the same absolute path the CDT uses so we patch the right object
from src.crew.services.graph.subgraphs.classification_decision_table_node import (
    ClassificationDecisionTableNodeSubgraph,
)
from src.crew.services.run_python_code_service import RunPythonCodeService
from src.shared.models.graph_nodes import (
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    PromptConfigData,
)
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.crew.utils.singleton_meta import SingletonMeta


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_state(variables: dict | None = None, node_name: str = "cdt_node") -> State:
    """Build a minimal State with a nodes entry initialised for node_name."""
    vars_dict = variables or {}
    state: State = {
        "state_history": [],
        "variables": DotDict(vars_dict),
        "system_variables": {
            "nodes": {
                node_name: {
                    "result_node": None,
                    "default_node": None,
                    "execution_order": 0,
                }
            },
            "execution_order": 0,
        },
        "execution_counts": {},
    }
    return state


def make_llm_data() -> LLMData:
    return LLMData(
        provider="openai",
        config=LLMConfigData(model="gpt-4o-mini"),
    )


def make_node_data(
    node_name: str = "cdt_node",
    condition_groups: list[ClassificationConditionGroupData] | None = None,
    prompts: dict[str, PromptConfigData] | None = None,
    default_next_node: str | None = None,
    next_error_node: str | None = None,
) -> ClassificationDecisionTableNodeData:
    return ClassificationDecisionTableNodeData(
        node_name=node_name,
        condition_groups=condition_groups or [],
        prompts=prompts or {},
        default_next_node=default_next_node,
        next_error_node=next_error_node,
    )


def make_subgraph(node_data: ClassificationDecisionTableNodeData) -> object:
    """Compile a ClassificationDecisionTableNodeSubgraph and return the compiled graph."""
    graph_builder = StateGraph(State)
    builder = ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=node_data,
        graph_builder=graph_builder,
        stop_event=StopEvent(),
        redis_service=MagicMock(),
    )
    return builder.build()


# ---------------------------------------------------------------------------
# Sandbox fake – executes generated code in-process
# ---------------------------------------------------------------------------


async def fake_run_code(
    self, python_code_data, inputs, stop_event=None, additional_global_kwargs=None
):
    ns: dict = {}
    exec(python_code_data.code, ns)  # noqa: S102
    ret = ns[python_code_data.entrypoint](**inputs)
    return {
        "returncode": 0,
        "result_data": json.dumps(ret),
        "stderr": "",
        "execution_id": "test",
    }


async def fake_run_code_error(
    self, python_code_data, inputs, stop_event=None, additional_global_kwargs=None
):
    return {
        "returncode": 1,
        "result_data": "null",
        "stderr": "boom",
        "execution_id": "test",
    }


# ---------------------------------------------------------------------------
# Singleton reset fixture
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def reset_singleton():
    """Clear the RunPythonCodeService singleton before each test."""
    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_matching_row_continue_false_routes_and_stops(monkeypatch):
    """First matching row with continue=False routes to its next_node.
    A later row's manipulation must NOT run (its variable stays unchanged)."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            manipulation="variables.row1_ran = True",
            next_node="node_A",
            continue_flag=False,
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="row2",
            expression="True",
            manipulation="variables.row2_ran = True",
            next_node="node_B",
            continue_flag=False,
            order=1,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"row1_ran": False, "row2_ran": False})

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_A"
    assert result["variables"]["row1_ran"] is True
    assert result["variables"]["row2_ran"] is False


@pytest.mark.asyncio
async def test_non_matching_first_row_falls_through_to_second(monkeypatch):
    """Non-matching first row is skipped; second matching row's next_node becomes result."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="False",
            next_node="node_A",
            continue_flag=False,
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="row2",
            expression="True",
            next_node="node_B",
            continue_flag=False,
            order=1,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state()

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_B"


@pytest.mark.asyncio
async def test_explicit_route_is_terminal_continue_ignored(monkeypatch):
    """An explicit next_node on a matched row is terminal regardless of continue_flag.

    row1 has next_node='A' and continue_flag=True. Evaluation must stop after row1;
    row2 must never execute. result_node == 'A'."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            manipulation="variables.row1_ran = True",
            next_node="A",
            continue_flag=True,
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="row2",
            expression="True",
            manipulation="variables.row2_ran = True",
            next_node="B",
            continue_flag=False,
            order=1,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"row1_ran": False, "row2_ran": False})

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "A"
    assert result["variables"]["row1_ran"] is True
    assert result["variables"]["row2_ran"] is False


@pytest.mark.asyncio
async def test_continue_true_no_route_falls_through_then_routes(monkeypatch):
    """continue_flag=True with no next_node falls through to the next condition.

    row1 has no next_node and continue_flag=True — falls through.
    row2 has next_node='B' — routes and stops.
    Both manipulations run; result_node == 'B'."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            manipulation="variables.row1_ran = True",
            next_node=None,
            continue_flag=True,
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="row2",
            expression="True",
            manipulation="variables.row2_ran = True",
            next_node="B",
            continue_flag=False,
            order=1,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"row1_ran": False, "row2_ran": False})

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "B"
    assert result["variables"]["row1_ran"] is True
    assert result["variables"]["row2_ran"] is True


@pytest.mark.asyncio
async def test_route_wins_over_continue_matches_qa_str(monkeypatch):
    """QA repro: row1 expression='True', next_node='node_A', continue_flag=True.
    row2 expression='True', no next_node, manipulation sets row2_ran.
    Evaluation must stop at row1; row2 must never execute."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            next_node="node_A",
            continue_flag=True,
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="row2",
            expression="True",
            manipulation="variables.row2_ran = True",
            next_node=None,
            continue_flag=False,
            order=1,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"row2_ran": False})

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_A"
    assert result["variables"]["row2_ran"] is False


@pytest.mark.asyncio
async def test_no_match_falls_back_to_default_next_node(monkeypatch):
    """No row matches → result_node == default_next_node."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="False",
            next_node="node_A",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(
        condition_groups=groups, default_next_node="default_node"
    )
    subgraph = make_subgraph(node_data)
    state = make_state()

    result = await subgraph.ainvoke(state)

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "default_node"
    )


@pytest.mark.asyncio
async def test_no_match_no_default_falls_back_to_end(monkeypatch):
    """No row matches and no default_next_node → result_node == END."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="False",
            next_node="node_A",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(condition_groups=groups, default_next_node=None)
    subgraph = make_subgraph(node_data)
    state = make_state()

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == END


@pytest.mark.asyncio
async def test_dock_visible_false_row_is_skipped(monkeypatch):
    """dock_visible=False row whose expression WOULD match is skipped entirely."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="hidden_row",
            expression="True",
            manipulation="variables.hidden_ran = True",
            next_node="should_not_be_set",
            dock_visible=False,
            continue_flag=False,
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="visible_row",
            expression="True",
            next_node="correct_node",
            dock_visible=True,
            continue_flag=False,
            order=1,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"hidden_ran": False})

    result = await subgraph.ainvoke(state)

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "correct_node"
    )
    assert result["variables"]["hidden_ran"] is False


@pytest.mark.asyncio
async def test_expression_sandbox_error_routes_to_next_error_node(monkeypatch):
    """Expression sandbox returncode!=0 → result_node == next_error_node."""
    monkeypatch.setattr(
        RunPythonCodeService, "run_code", fake_run_code_error, raising=True
    )

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            next_node="node_A",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(condition_groups=groups, next_error_node="error_node")
    subgraph = make_subgraph(node_data)
    state = make_state()

    result = await subgraph.ainvoke(state)

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    )


@pytest.mark.asyncio
async def test_expression_sandbox_error_no_error_node_routes_to_end(monkeypatch):
    """Expression sandbox returncode!=0 with no next_error_node → result_node == END."""
    monkeypatch.setattr(
        RunPythonCodeService, "run_code", fake_run_code_error, raising=True
    )

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            next_node="node_A",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(condition_groups=groups, next_error_node=None)
    subgraph = make_subgraph(node_data)
    state = make_state()

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == END


@pytest.mark.asyncio
async def test_field_expressions_bare_value_and_operator_prefix(monkeypatch):
    """field_expressions: bare value `'"start"'` matches when status=='start';
    operator-prefix `'> 5'` matches when count > 5."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            field_expressions={
                "status": '"start"',  # bare value → status == "start"
                "count": "> 5",  # operator prefix → count > 5
            },
            next_node="matched_node",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"status": "start", "count": 10})

    result = await subgraph.ainvoke(state)

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "matched_node"
    )


@pytest.mark.asyncio
async def test_field_expressions_no_match_when_values_differ(monkeypatch):
    """field_expressions do not match when state vars don't satisfy them."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            field_expressions={
                "status": '"start"',
                "count": "> 5",
            },
            next_node="matched_node",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(condition_groups=groups, default_next_node="fallback")
    subgraph = make_subgraph(node_data)
    state = make_state({"status": "end", "count": 3})

    result = await subgraph.ainvoke(state)

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "fallback"


@pytest.mark.asyncio
async def test_manipulation_writes_back_to_state_variables(monkeypatch):
    """field_manipulations with a bare key write back to state['variables'].

    The engine prefixes bare keys with `variables.` so `{"score": "score + 10"}`
    generates `variables.score = score + 10`, which is captured by the write-back
    path. The main manipulation also runs and updates its target variable.
    """
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            field_manipulations={"score": "score + 10"},
            manipulation="variables.label = 'updated'",
            next_node="done",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"score": 5, "label": "original"})

    result = await subgraph.ainvoke(state)

    assert result["variables"]["score"] == 15
    assert result["variables"]["label"] == "updated"


@pytest.mark.asyncio
async def test_field_manipulations_already_prefixed_key_not_double_prefixed(
    monkeypatch,
):
    """field_manipulations with an already-prefixed key (`variables.score`) must not
    become `variables.variables.score` — the engine skips the prefix when already present."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1",
            expression="True",
            field_manipulations={"variables.score": "score + 1"},
            next_node="done",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(condition_groups=groups)
    subgraph = make_subgraph(node_data)
    state = make_state({"score": 10})

    result = await subgraph.ainvoke(state)

    assert result["variables"]["score"] == 11
    assert "variables" not in result["variables"]


@pytest.mark.asyncio
async def test_prompt_with_output_schema_calls_llm_and_stores_result(monkeypatch):
    """Prompt with output_schema: acompletion called with json_schema response_format;
    parsed dict stored at result_variable; variable_mappings extract field into state var."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)

    output_schema = {
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": ["label"],
    }

    prompt_config = PromptConfigData(
        prompt_text="Classify the following: {text}",
        llm_data=make_llm_data(),
        output_schema=output_schema,
        result_variable="classification_result",
        variable_mappings={"extracted_label": "label"},
    )

    groups = [
        ClassificationConditionGroupData(
            group_name="prompt_row",
            expression="True",
            prompt_id="classify",
            next_node="after_prompt",
            continue_flag=False,
            order=0,
        ),
    ]
    node_data = make_node_data(
        condition_groups=groups,
        prompts={"classify": prompt_config},
    )
    subgraph = make_subgraph(node_data)
    state = make_state({"text": "hello world"})

    mock_response = MagicMock()
    mock_response.usage.total_tokens = 42
    mock_response.usage.prompt_tokens = 20
    mock_response.usage.completion_tokens = 22
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"label": "positive"}'

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
        mock_completion.return_value = mock_response

        result = await subgraph.ainvoke(state)

        assert mock_completion.called
        call_kwargs = mock_completion.call_args.kwargs
        response_format = call_kwargs.get("response_format") or {}
        assert response_format.get("type") == "json_schema"

    assert result["variables"]["classification_result"] == {"label": "positive"}
    assert result["variables"]["extracted_label"] == "positive"
    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "after_prompt"
    )
