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
from src.shared.models import PythonCodeData
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
# Sandbox fake - executes generated code in-process
# ---------------------------------------------------------------------------


# Mirrors the module globals the sandbox's wrap_code sets up around user code
# (get_secret is left out: epicstaff_secrets only exists in the sandbox venv).
_SANDBOX_MODULE_PRELUDE = """
import errno
import os
import socket
import sys
import json
from dotdict import DotDict, DotObject, DotList
"""


async def fake_run_code(
    self,
    python_code_data,
    inputs,
    stop_event=None,
    additional_global_kwargs=None,
    storage_credentials=None,
):
    ns: dict = {}
    exec(_SANDBOX_MODULE_PRELUDE + python_code_data.code, ns)  # noqa: S102
    # wrap_code calls the entrypoint with DotDict-wrapped kwargs.
    ret = ns[python_code_data.entrypoint](**DotDict(inputs))
    return {
        "returncode": 0,
        "result_data": json.dumps(ret),
        "stderr": "",
        "execution_id": "test",
    }


async def fake_run_code_error(
    self,
    python_code_data,
    inputs,
    stop_event=None,
    additional_global_kwargs=None,
    storage_credentials=None,
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


def row(order, expression=None, next_node=None, **fields):
    return ClassificationConditionGroupData(
        group_name=f"row{order}", order=order, expression=expression, next_node=next_node, **fields
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("groups", "variables", "node_overrides", "expected_route", "expected_variables"),
    [
        pytest.param(
            [row(0, "True", "node_A", manipulation="variables.ran = 'row0'"),
             row(1, "True", "node_B", manipulation="variables.ran = 'row1'")],
            {"ran": None}, {}, "node_A", {"ran": "row0"},
            id="first-match-routes-and-later-rows-never-run",
        ),
        pytest.param(
            [row(0, "False", "node_A"), row(1, "True", "node_B")],
            {}, {}, "node_B", {},
            id="non-matching-row-falls-through",
        ),
        pytest.param(
            [row(0, "True", "node_A", continue_flag=True),
             row(1, "True", manipulation="variables.ran = 'row1'")],
            {"ran": None}, {}, "node_A", {"ran": None},
            id="explicit-route-is-terminal-even-with-continue",
        ),
        pytest.param(
            [row(0, "True", continue_flag=True, manipulation="variables.ran = ['row0']"),
             row(1, "True", "node_B", manipulation="variables.ran = variables.ran + ['row1']")],
            {"ran": []}, {}, "node_B", {"ran": ["row0", "row1"]},
            id="continue-without-route-runs-and-falls-through",
        ),
        pytest.param(
            [row(0, "False", "node_A")],
            {}, {"default_next_node": "default_node"}, "default_node", {},
            id="no-match-uses-default",
        ),
        pytest.param(
            [row(0, "False", "node_A")], {}, {}, END, {},
            id="no-match-no-default-ends",
        ),
        pytest.param(
            [row(0, "True", "hidden", dock_visible=False, manipulation="variables.ran = 'hidden'"),
             row(1, "True", "visible")],
            {"ran": None}, {}, "visible", {"ran": None},
            id="hidden-row-is-skipped",
        ),
        pytest.param(
            # A bare value means `field == value`; an operator prefix is applied to the field.
            [row(0, next_node="matched", field_expressions={"status": '"start"', "count": "> 5"})],
            {"status": "start", "count": 10}, {"default_next_node": "fallback"}, "matched", {},
            id="field-expressions-match",
        ),
        pytest.param(
            [row(0, next_node="matched", field_expressions={"status": '"start"', "count": "> 5"})],
            {"status": "end", "count": 3}, {"default_next_node": "fallback"}, "fallback", {},
            id="field-expressions-do-not-match",
        ),
        pytest.param(
            [row(0, "True", "done", field_manipulations={"score": "score + 10"},
                 manipulation="variables.label = 'updated'")],
            {"score": 5, "label": "original"}, {}, "done", {"score": 15, "label": "updated"},
            id="field-and-main-manipulations-write-back",
        ),
        pytest.param(
            [row(0, "True", "done", field_manipulations={"variables.score": "score + 1"})],
            {"score": 10}, {}, "done", {"score": 11},
            id="already-prefixed-field-manipulation",
        ),
    ],
)
async def test_routing(
    monkeypatch, groups, variables, node_overrides, expected_route, expected_variables
):
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)
    subgraph = make_subgraph(make_node_data(condition_groups=groups, **node_overrides))

    result = await subgraph.ainvoke(make_state(variables))

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == expected_route
    assert {name: result["variables"][name] for name in expected_variables} == expected_variables
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


async def run_prompt_row_and_capture_acompletion_kwargs(
    monkeypatch, llm_config: LLMConfigData, provider: str = "openai"
) -> dict:
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)
    prompt_config = PromptConfigData(
        prompt_text="Classify the following: {text}",
        llm_data=LLMData(provider=provider, config=llm_config),
        output_schema={
            "type": "object",
            "properties": {"label": {"type": "string"}},
            "required": ["label"],
        },
        result_variable="classification_result",
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
    subgraph = make_subgraph(
        make_node_data(condition_groups=groups, prompts={"classify": prompt_config})
    )

    mock_response = MagicMock()
    mock_response.usage.total_tokens = 1
    mock_response.usage.prompt_tokens = 1
    mock_response.usage.completion_tokens = 0
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = '{"label": "positive"}'

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
        mock_completion.return_value = mock_response
        await subgraph.ainvoke(make_state({"text": "hello world"}))

    assert mock_completion.call_count == 1
    return mock_completion.call_args.kwargs


@pytest.mark.asyncio
async def test_prompt_llm_call_forwards_reasoning_effort(monkeypatch):
    call_kwargs = await run_prompt_row_and_capture_acompletion_kwargs(
        monkeypatch,
        LLMConfigData(model="gpt-5-mini", reasoning_effort="high", temperature=0.2),
    )

    assert call_kwargs["reasoning_effort"] == "high"
    assert call_kwargs["temperature"] == 0.2
    assert call_kwargs["model"] == "openai/gpt-5-mini"


@pytest.mark.asyncio
async def test_prompt_llm_call_omits_unset_generation_params(monkeypatch):
    call_kwargs = await run_prompt_row_and_capture_acompletion_kwargs(
        monkeypatch, LLMConfigData(model="gpt-4o-mini")
    )

    for unset_param in (
        "reasoning_effort",
        "temperature",
        "top_p",
        "stop",
        "max_tokens",
        "presence_penalty",
        "frequency_penalty",
        "logit_bias",
        "seed",
        "timeout",
    ):
        assert unset_param not in call_kwargs
    assert call_kwargs["stream"] is False
    assert call_kwargs["response_format"]["type"] == "json_schema"


@pytest.mark.asyncio
async def test_prompt_llm_call_drops_sampling_params_anthropic_rejects_with_thinking(
    monkeypatch,
):
    call_kwargs = await run_prompt_row_and_capture_acompletion_kwargs(
        monkeypatch,
        LLMConfigData(
            model="claude-sonnet-4-6", temperature=0.5, top_p=0.9, reasoning_effort="high"
        ),
        provider="anthropic",
    )

    assert call_kwargs["model"] == "anthropic/claude-sonnet-4-6"
    assert call_kwargs["reasoning_effort"] == "high"
    assert "temperature" not in call_kwargs
    assert "top_p" not in call_kwargs


async def fake_run_code_raises(
    self,
    python_code_data,
    inputs,
    stop_event=None,
    additional_global_kwargs=None,
    storage_credentials=None,
):
    raise RuntimeError("sandbox unreachable")


_FAILING_CODE = PythonCodeData(
    venv_name="default", code="def main(): pass", entrypoint="main", libraries=[]
)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "run_code, expression, node_data_overrides, expected_route",
    [
        (fake_run_code_error, "True", {}, "error_node"),
        (fake_run_code_raises, "True", {}, "error_node"),
        (fake_run_code_error, None, {"pre_python_code": _FAILING_CODE}, "error_node"),
        (fake_run_code_error, None, {"post_python_code": _FAILING_CODE}, "error_node"),
        (fake_run_code_error, "True", {"next_error_node": None}, END),
    ],
    ids=[
        "condition-error",
        "condition-unexpected-error",
        "pre-computation",
        "post-computation",
        "no-error-node-ends",
    ],
)
async def test_error_route_emits_finish_after_error(
    monkeypatch, run_code, expression, node_data_overrides, expected_route
):
    """Every error route closes the CDT run with a finish message, so the UI stops
    grouping the next node's messages under the CDT."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", run_code, raising=True)

    groups = [
        ClassificationConditionGroupData(
            group_name="row1", expression=expression, continue_flag=False, order=0
        ),
    ]
    node_data = make_node_data(
        condition_groups=groups, next_error_node="error_node"
    ).model_copy(update=node_data_overrides)
    redis_service = MagicMock()
    subgraph = ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=node_data,
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        redis_service=redis_service,
    ).build()

    result = await subgraph.ainvoke(make_state())

    messages = published_messages(redis_service)
    message_types = [message["message_type"] for message in messages]
    assert message_types[0] == "start"
    assert message_types[-2:] == ["error", "finish"]
    assert messages[-1]["output"] == expected_route
    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == expected_route


# ---------------------------------------------------------------------------
# Batched condition evaluation
# ---------------------------------------------------------------------------


def record_run_code(monkeypatch) -> list[dict]:
    """Patch run_code with fake_run_code and return the inputs of every call."""
    calls: list[dict] = []

    async def recording_run_code(
        self,
        python_code_data,
        inputs,
        stop_event=None,
        additional_global_kwargs=None,
        storage_credentials=None,
    ):
        calls.append(inputs)
        return await fake_run_code(self, python_code_data, inputs, stop_event)

    monkeypatch.setattr(RunPythonCodeService, "run_code", recording_run_code, raising=True)
    return calls


def expression_batch_calls(calls: list[dict]) -> list[dict]:
    return [inputs for inputs in calls if "expressions" in inputs]


def build_subgraph_with_redis(node_data: ClassificationDecisionTableNodeData):
    redis_service = MagicMock()
    subgraph = ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=node_data,
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        redis_service=redis_service,
    ).build()
    return subgraph, redis_service


def published_messages(redis_service: MagicMock) -> list[dict]:
    return [
        json.loads(added.args[1])["message_data"]
        for added in redis_service.add_graph_message.call_args_list
    ]


@pytest.mark.asyncio
async def test_non_matching_rows_before_match_share_one_sandbox_call(monkeypatch):
    calls = record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name=f"miss{index}",
            expression="count > 100",
            next_node="wrong",
            order=index,
        )
        for index in range(3)
    ] + [
        ClassificationConditionGroupData(
            group_name="hit", expression="count == 7", next_node="node_hit", order=3
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(condition_groups=groups)
    )

    result = await subgraph.ainvoke(make_state({"count": 7}))

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_hit"
    assert len(calls) == 1
    assert len(calls[0]["expressions"]) == 4
    condition_results = [
        (message["group_name"], message["result"])
        for message in published_messages(redis_service)
        if message["message_type"] == "condition_group"
    ]
    assert condition_results == [
        ("miss0", False),
        ("miss1", False),
        ("miss2", False),
        ("hit", True),
    ]


@pytest.mark.asyncio
async def test_broken_expressions_after_the_match_are_never_evaluated(monkeypatch):
    calls = record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="hit", expression="True", next_node="node_A", order=0
        ),
        ClassificationConditionGroupData(
            group_name="syntax_error", expression="this is (( not python", order=1
        ),
        ClassificationConditionGroupData(
            group_name="name_error", expression="undefined_name == 1", order=2
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(condition_groups=groups, next_error_node="error_node")
    )

    result = await subgraph.ainvoke(make_state())

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_A"
    assert len(calls) == 1
    message_types = [
        message["message_type"] for message in published_messages(redis_service)
    ]
    assert "error" not in message_types
    assert message_types.count("condition_group") == 1


@pytest.mark.asyncio
async def test_broken_expression_before_match_routes_to_error_after_earlier_rows(
    monkeypatch,
):
    record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="miss", expression="False", next_node="wrong", order=0
        ),
        ClassificationConditionGroupData(
            group_name="broken",
            expression="undefined_name > 1",
            next_node="wrong",
            order=1,
        ),
        ClassificationConditionGroupData(
            group_name="would_hit", expression="True", next_node="wrong", order=2
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(condition_groups=groups, next_error_node="error_node")
    )

    result = await subgraph.ainvoke(make_state())

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    )
    messages = published_messages(redis_service)
    assert [message["message_type"] for message in messages] == [
        "start",
        "condition_group",
        "error",
        "finish",
    ]
    assert messages[1]["group_name"] == "miss"
    assert messages[1]["result"] is False
    error_details = messages[2]["details"]
    assert error_details.startswith(
        "Error in condition 'broken': Expression execution failed:"
    )
    assert "NameError" in error_details


@pytest.mark.asyncio
async def test_non_boolean_expression_routes_to_error(monkeypatch):
    record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="not_bool", expression="42", next_node="wrong", order=0
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(condition_groups=groups, next_error_node="error_node")
    )

    result = await subgraph.ainvoke(make_state())

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    )
    error_message = next(
        message
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    )
    assert "Expression must return a boolean value" in error_message["details"]


@pytest.mark.asyncio
async def test_continue_row_manipulation_is_seen_by_the_next_batch(monkeypatch):
    calls = record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="advance",
            expression='stage == "first"',
            manipulation='variables.stage = "second"',
            continue_flag=True,
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="still_first",
            expression='stage == "first"',
            next_node="wrong",
            order=1,
        ),
        ClassificationConditionGroupData(
            group_name="now_second",
            expression='stage == "second"',
            next_node="node_B",
            order=2,
        ),
    ]
    subgraph, _ = build_subgraph_with_redis(make_node_data(condition_groups=groups))

    result = await subgraph.ainvoke(make_state({"stage": "first"}))

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_B"
    assert result["variables"]["stage"] == "second"
    batches = expression_batch_calls(calls)
    assert [len(batch["expressions"]) for batch in batches] == [3, 2]
    assert [batch["variables"]["stage"] for batch in batches] == ["first", "second"]


@pytest.mark.asyncio
async def test_row_without_expression_matches_without_a_sandbox_call(monkeypatch):
    calls = record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="miss", expression="False", next_node="wrong", order=0
        ),
        ClassificationConditionGroupData(
            group_name="catch_all", next_node="node_C", order=1
        ),
    ]
    subgraph, _ = build_subgraph_with_redis(make_node_data(condition_groups=groups))

    result = await subgraph.ainvoke(make_state())

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_C"
    assert [batch["expressions"] for batch in calls] == [["(False)"]]


@pytest.mark.asyncio
async def test_expression_can_use_sandbox_module_globals(monkeypatch):
    record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="json_row",
            expression='json.loads(payload)["kind"] == "order" and DotDict is not None',
            next_node="node_order",
            order=0,
        ),
    ]
    subgraph, _ = build_subgraph_with_redis(make_node_data(condition_groups=groups))

    result = await subgraph.ainvoke(make_state({"payload": '{"kind": "order"}'}))

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_order"
    )


@pytest.mark.asyncio
async def test_mutation_in_one_row_does_not_leak_into_the_next_row(monkeypatch):
    calls = record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="mutates",
            expression="bool(items.append(1))",
            next_node="wrong",
            order=0,
        ),
        ClassificationConditionGroupData(
            group_name="sees_original",
            expression="len(items) == 0",
            next_node="node_clean",
            order=1,
        ),
    ]
    subgraph, _ = build_subgraph_with_redis(make_node_data(condition_groups=groups))

    result = await subgraph.ainvoke(make_state({"items": []}))

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_clean"
    )
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_exit_in_expression_is_reported_against_its_row(monkeypatch):
    record_run_code(monkeypatch)
    groups = [
        ClassificationConditionGroupData(
            group_name="miss", expression="False", next_node="wrong", order=0
        ),
        ClassificationConditionGroupData(
            group_name="exits", expression="exit(3)", next_node="wrong", order=1
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(condition_groups=groups, next_error_node="error_node")
    )

    result = await subgraph.ainvoke(make_state())

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    )
    error_message = next(
        message
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    )
    assert error_message["details"].startswith(
        "Error in condition 'exits': Expression execution failed: SystemExit"
    )


# ---------------------------------------------------------------------------
# Path resolution safety
# ---------------------------------------------------------------------------


def test_resolve_path_resolves_legitimate_dot_and_bracket_paths():
    # Legitimate dot, direct lookup, and bracket paths stay working.
    resolve = ClassificationDecisionTableNodeSubgraph._resolve_path
    ctx = {
        "variables": DotDict(
            {
                "chat_id": "abc",
                "index": 1,
                "messages": [DotDict({"text": "first"}), DotDict({"text": "second"})],
            }
        ),
        "session_id": 42,
    }

    assert resolve("variables.chat_id", ctx) == "abc"
    assert resolve("session_id", ctx) == 42
    assert resolve("variables.messages[variables.index].text", ctx) == "second"


def test_resolve_path_rejects_dunder_dot_token():
    # A dunder dot token must not reach Python internals.
    resolve = ClassificationDecisionTableNodeSubgraph._resolve_path
    ctx = {"variables": DotDict({"chat_id": "abc"})}

    with pytest.raises(KeyError):
        resolve("variables.__class__", ctx)
    with pytest.raises(KeyError):
        resolve("variables.__class__.__init__.__globals__", ctx)


def test_resolve_path_allows_bracket_access_to_underscore_domain_key():
    # Bracket access is item lookup, not getattr — an underscore domain key
    # must still resolve rather than be over-blocked.
    resolve = ClassificationDecisionTableNodeSubgraph._resolve_path
    ctx = {"variables": DotDict({"attr_name": "_secret", "_secret": "leak"})}

    assert resolve("variables[variables.attr_name]", ctx) == "leak"


@pytest.mark.asyncio
async def test_batch_run_failure_names_the_row_range(monkeypatch):
    monkeypatch.setattr(
        RunPythonCodeService, "run_code", fake_run_code_error, raising=True
    )
    groups = [
        ClassificationConditionGroupData(
            group_name="first", expression="False", next_node="wrong", order=0
        ),
        ClassificationConditionGroupData(
            group_name="second", expression="False", next_node="wrong", order=1
        ),
        ClassificationConditionGroupData(
            group_name="last", expression="True", next_node="wrong", order=2
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(condition_groups=groups, next_error_node="error_node")
    )

    result = await subgraph.ainvoke(make_state())

    assert (
        result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    )
    error_message = next(
        message
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    )
    assert error_message["details"] == (
        "Error evaluating conditions from 'first' to 'last': "
        "Expression execution failed: boom"
    )
