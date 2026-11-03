"""
Tests for ClassificationDecisionTableNodeSubgraph.

Sandbox (RunPythonCodeService.run_code) is patched to execute the generated code
in-process so expression/manipulation logic is fully exercised.
LLM calls (litellm.acompletion) are replaced with AsyncMock.

NOTE: Patch `services.run_python_code_service.RunPythonCodeService`, the module path the
CDT subgraph and every other caller import; a second import path would be a second
class with its own singleton.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from dotdict import DotDict
from langgraph.graph import END, StateGraph
from litellm.types.utils import ModelResponse, Usage
from loguru import logger

from models.state import State
from services.graph.events import StopEvent

from src.crew.services.graph.subgraphs.classification_decision_table_node import (
    ClassificationDecisionTableNodeSubgraph,
)
from services.run_python_code_service import RunPythonCodeService
from src.shared.models.graph_nodes import (
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    PromptConfigData,
)
from src.shared.models import PythonCodeData
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.models.sessions import TokenUsage
from src.shared.models.system_one import (
    NoulAnswer,
    SystemOneConfigData,
    SystemOneResult,
)
from src.shared.system_one.adapter import SYSTEM_ONE_ADAPTERS, SystemOneError
from src.shared.system_one.llm_adapter import LlmSystemOneAdapter
from src.shared.system_one.openai_adapter import OpenAIDecisionsAdapter
from src.shared.system_one.typesafe_adapter import TypeSafeAdapter
from utils.singleton_meta import SingletonMeta


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


def recording_redis_service() -> MagicMock:
    redis_service = MagicMock()
    redis_service.aadd_graph_message = AsyncMock()
    return redis_service


def make_subgraph(node_data: ClassificationDecisionTableNodeData) -> object:
    """Compile a ClassificationDecisionTableNodeSubgraph and return the compiled graph."""
    graph_builder = StateGraph(State)
    builder = ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=node_data,
        graph_builder=graph_builder,
        stop_event=StopEvent(),
        redis_service=recording_redis_service(),
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
    assert call_kwargs["model"] == "gpt-5-mini"


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
    code="def main(): pass", entrypoint="main"
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
    redis_service = recording_redis_service()
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
    redis_service = recording_redis_service()
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
        for added in redis_service.aadd_graph_message.await_args_list
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


# ---------------------------------------------------------------------------
# Exception text sanitization
# ---------------------------------------------------------------------------


_SENSITIVE_EXCEPTION_TEXT = "sk-live-abcdef at https://internal-llm.epicstaff.local:8443"


def first_error_message(redis_service: MagicMock) -> dict:
    return next(
        message
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    )


@pytest.mark.asyncio
async def test_llm_failure_reports_the_prompt_without_provider_exception_text(monkeypatch):
    """A provider failure names the prompt; the provider's own message, which can
    quote the API key and endpoint, stays in the logs."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)
    prompt_config = PromptConfigData(
        prompt_text="Classify {text}",
        llm_data=make_llm_data(),
        result_variable="classification_result",
    )
    groups = [
        ClassificationConditionGroupData(
            group_name="prompt_row",
            expression="True",
            prompt_id="classify",
            next_node="after_prompt",
            order=0,
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(
            condition_groups=groups,
            prompts={"classify": prompt_config},
            next_error_node="error_node",
        )
    )

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_completion:
        mock_completion.side_effect = RuntimeError(_SENSITIVE_EXCEPTION_TEXT)
        result = await subgraph.ainvoke(make_state({"text": "hello"}))

    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    assert first_error_message(redis_service)["details"] == (
        "Error in condition 'prompt_row': LLM call failed for prompt 'classify'"
    )


# ---------------------------------------------------------------------------
# System One entries
# ---------------------------------------------------------------------------


class FakeSystemOneAdapter:
    """Answers every question with a fixed noul and records the state it got."""

    def __init__(self, noul: float = 0.92, error: Exception | None = None, cost: float = 0.0):
        self.noul, self.error, self.cost, self.states = noul, error, cost, []

    async def evaluate(self, *, config, state, questions):
        self.states.append(state)
        if self.error:
            raise self.error
        answers = {name: NoulAnswer(type="noul", noul=self.noul) for name in questions}
        result = SystemOneResult(answers=answers, provider=config.provider, model_version="fake-1")
        return result, TokenUsage(prompt_tokens=7, total_tokens=7, total_cost_usd=self.cost)


FAKE_CONFIG = SystemOneConfigData(id=1, provider="fake")


def system_one_node(
    config: SystemOneConfigData | None = FAKE_CONFIG,
    questions: dict | None = None,
    input_map: dict | None = None,
):
    entry = PromptConfigData(
        prompt_text="",
        kind="system_one",
        system_one_config=config,
        questions=(
            {"is_engineering": {"type": "noul", "instructions": "Engineering?"}}
            if questions is None
            else questions
        ),
        input_map={"company": "variables.company"} if input_map is None else input_map,
        result_variable="company_check",
    )
    rows = [
        row(0, prompt_id="company_check", continue_flag=True),
        row(1, "company_check.answers.is_engineering.noul > 0.8", "eng_branch"),
    ]
    return make_node_data(
        condition_groups=rows,
        prompts={"company_check": entry},
        default_next_node="other",
        next_error_node="error_node",
    )


def result_node(result) -> str:
    return result["system_variables"]["nodes"]["cdt_node"]["result_node"]


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)


@pytest.mark.asyncio
async def test_a_system_one_row_stores_answers_and_the_next_row_routes_on_them(
    monkeypatch, sandbox
):
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "fake", FakeSystemOneAdapter(noul=0.92))
    subgraph, _ = build_subgraph_with_redis(system_one_node())

    result = await subgraph.ainvoke(make_state({"company": "Acme"}))

    assert result_node(result) == "eng_branch"
    assert result["variables"]["company_check"]["answers"]["is_engineering"]["noul"] == 0.92


@pytest.mark.asyncio
async def test_below_threshold_takes_the_default_path(monkeypatch, sandbox):
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "fake", FakeSystemOneAdapter(noul=0.5))
    subgraph, _ = build_subgraph_with_redis(system_one_node())

    result = await subgraph.ainvoke(make_state({"company": "Acme"}))

    assert result_node(result) == "other"
    assert result["variables"]["company_check"]["answers"]["is_engineering"]["noul"] == 0.5


TYPESAFE_RECORDED = (
    '{"model":"jev-1.14.0","answers":{"is_engineering":{"type":"noul","noul":0.93},'
    '"department":{"type":"choice","choice":"engineering","confidence":1.0,'
    '"probabilities":{"engineering":1.0,"sales":0.0}},'
    '"size":{"type":"score","score":0.48,"confidence":0.26,'
    '"legend":{"0":"small","1":"medium","2":"large"},'
    '"probabilities":{"0":0.53,"1":0.45,"2":0.02}}},'
    '"usage":{"input_tokens":377,"output_tokens":64}}'
)
OPENAI_RECORDED = (
    '{"model":"gpt-6-luna","answers":[{"type":"predicate","name":"is_engineering",'
    '"probability":0.95},{"type":"choice","name":"department","choice":"engineering",'
    '"probabilities":[{"value":"engineering","probability":0.97},'
    '{"value":"sales","probability":0.03}],"confidence":0.94},'
    '{"type":"score","name":"size","score":1.0,"probabilities":['
    '{"value":0,"label":"small","probability":0.0},{"value":1,"label":"medium",'
    '"probability":1.0},{"value":2,"label":"large","probability":0.0}],"confidence":1.0}],'
    '"usage":{"input_tokens":420,"output_tokens":0}}'
)
LLM_MODEL = "gpt-4o-mini"


def real_typesafe_config() -> SystemOneConfigData:
    return SystemOneConfigData(id=1, provider="typesafe", model_name="jev-1.14.0", api_key="ts-key")


def real_openai_config() -> SystemOneConfigData:
    return SystemOneConfigData(id=3, provider="openai", model_name="gpt-6-luna", api_key="sk-key")


def real_llm_config() -> SystemOneConfigData:
    return SystemOneConfigData(
        id=2,
        provider="llm",
        llm_data=LLMData(provider="openai", config=LLMConfigData(model=LLM_MODEL)),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("config", "expected_provider", "expected_model_version"),
    [
        pytest.param(real_typesafe_config(), "typesafe", "jev-1.14.0", id="typesafe"),
        pytest.param(real_llm_config(), "llm", LLM_MODEL, id="llm"),
        pytest.param(real_openai_config(), "openai", "gpt-6-luna", id="openai"),
    ],
)
async def test_switching_the_provider_needs_no_table_change(
    monkeypatch, sandbox, config, expected_provider, expected_model_version
):
    typesafe = TypeSafeAdapter(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, content=TYPESAFE_RECORDED)
        )
    )
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "typesafe", typesafe)
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "llm", LlmSystemOneAdapter())
    openai = OpenAIDecisionsAdapter(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=OPENAI_RECORDED))
    )
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "openai", openai)
    llm_reply = ModelResponse(
        model=LLM_MODEL,
        choices=[
            {
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"answers": {"is_engineering": {"noul": 0.92}}}),
                }
            }
        ],
        usage=Usage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )
    subgraph, redis_service = build_subgraph_with_redis(system_one_node(config))

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=llm_reply):
        result = await subgraph.ainvoke(make_state({"company": "Acme"}))

    assert result_node(result) == "eng_branch"
    message = next(
        m for m in published_messages(redis_service) if m["message_type"] == "classification_prompt"
    )
    assert message["provider"] == expected_provider
    assert message["model_version"] == expected_model_version


@pytest.mark.asyncio
async def test_a_new_provider_runs_through_the_cdt_with_one_registry_entry(monkeypatch, sandbox):
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "fake", FakeSystemOneAdapter(noul=0.99))
    subgraph, _ = build_subgraph_with_redis(system_one_node())

    result = await subgraph.ainvoke(make_state({"company": "Acme"}))

    assert result_node(result) == "eng_branch"


@pytest.mark.asyncio
async def test_the_message_carries_provider_model_version_state_and_raw_result(
    monkeypatch, sandbox
):
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "fake", FakeSystemOneAdapter(cost=0.0000158))
    subgraph, redis_service = build_subgraph_with_redis(system_one_node())

    await subgraph.ainvoke(make_state({"company": "Acme"}))

    message = next(
        m for m in published_messages(redis_service) if m["message_type"] == "classification_prompt"
    )
    stored = {
        "answers": {"is_engineering": {"type": "noul", "noul": 0.92}},
        "provider": "fake",
        "model_version": "fake-1",
    }
    assert message["provider"] == "fake"
    assert message["model_version"] == "fake-1"
    assert message["prompt_text"] == json.dumps({"company": "Acme"}, indent=2)
    assert message["raw_response"] == json.dumps(stored)
    assert message["parsed_result"] == stored
    assert message["result_variable"] == "company_check"
    assert message["usage"]["total_cost_usd"] == 0.0000158


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("node_kwargs", "adapter_error", "expected"),
    [
        pytest.param(
            {"config": None},
            None,
            "Error in condition 'row0': System One entry 'company_check' has no config.",
            id="no-config",
        ),
        pytest.param(
            {"questions": {}},
            None,
            "Error in condition 'row0': System One entry 'company_check' has no valid questions.",
            id="no-questions",
        ),
        pytest.param(
            {"questions": {"1bad": {"type": "noul", "instructions": "x"}}},
            None,
            "Error in condition 'row0': System One entry 'company_check' has no valid questions.",
            id="invalid-question-name",
        ),
        pytest.param(
            {"input_map": {}},
            None,
            "Error in condition 'row0': System One entry 'company_check' has no input values.",
            id="empty-input-map",
        ),
        pytest.param(
            {"input_map": {"company": "variables.missing"}},
            None,
            "Error in condition 'row0': System One entry 'company_check' has no input values.",
            id="every-input-value-is-none",
        ),
        pytest.param(
            {},
            SystemOneError("TypeSafe rate limit reached."),
            "Error in condition 'row0': System One call failed for prompt 'company_check': "
            "TypeSafe rate limit reached.",
            id="adapter-reports-a-system-one-error",
        ),
        pytest.param(
            {},
            RuntimeError("401 key=ts-secret"),
            "Error in condition 'row0': System One call failed for prompt 'company_check': "
            "System One provider 'fake' failed.",
            id="adapter-crashes-with-provider-text",
        ),
    ],
)
async def test_a_failing_system_one_entry_takes_the_error_path_with_our_own_message(
    monkeypatch, sandbox, node_kwargs, adapter_error, expected
):
    adapter = FakeSystemOneAdapter(error=adapter_error)
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "fake", adapter)
    subgraph, redis_service = build_subgraph_with_redis(system_one_node(**node_kwargs))

    result = await subgraph.ainvoke(make_state({"company": "Acme"}))

    assert result_node(result) == "error_node"
    details = first_error_message(redis_service)["details"]
    assert details == expected
    assert "ts-secret" not in details
    if adapter_error is None:
        assert adapter.states == []


@pytest.mark.asyncio
async def test_input_map_missing_path_and_datetime_still_go_out(monkeypatch):
    # Called directly: a datetime in the state already breaks the session messages
    # of a full run, so only this step is under test.
    adapter = FakeSystemOneAdapter()
    monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "fake", adapter)
    when = datetime(2026, 1, 1, 12, 30, tzinfo=UTC)
    node_data = system_one_node(input_map={"a": "variables.missing", "b": "variables.when"})
    node = ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=node_data,
        graph_builder=StateGraph(State),
        stop_event=StopEvent(),
        redis_service=recording_redis_service(),
    )

    await node._execute_prompt("company_check", make_state({"when": when}))

    assert adapter.states == [{"a": None, "b": str(when)}]


@pytest.mark.asyncio
async def test_llm_entries_are_unchanged(sandbox):
    prompt_config = PromptConfigData(
        prompt_text="Classify {text}",
        llm_data=make_llm_data(),
        result_variable="classification_result",
    )
    groups = [row(0, "True", "after_prompt", prompt_id="classify")]
    subgraph, redis_service = build_subgraph_with_redis(
        make_node_data(condition_groups=groups, prompts={"classify": prompt_config})
    )
    completion = MagicMock()
    completion.choices = [MagicMock()]
    completion.choices[0].message.content = '{"label": "a"}'
    completion.usage.prompt_tokens = completion.usage.completion_tokens = 1
    completion.usage.total_tokens = 2

    with patch("litellm.acompletion", new_callable=AsyncMock, return_value=completion):
        result = await subgraph.ainvoke(make_state({"text": "hello"}))

    assert result_node(result) == "after_prompt"
    message = next(
        m for m in published_messages(redis_service) if m["message_type"] == "classification_prompt"
    )
    assert message["provider"] is None
    assert message["model_version"] is None
    assert message["prompt_text"] == "Classify hello"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "node_data_overrides",
    [
        pytest.param(
            {"pre_python_code": _FAILING_CODE, "pre_output_variable_path": "variables.__class__.status"},
            id="pre-computation",
        ),
        pytest.param(
            {"post_python_code": _FAILING_CODE, "post_output_variable_path": "variables.__class__.status"},
            id="post-computation",
        ),
    ],
)
async def test_underscore_computation_output_path_routes_to_error_without_a_sandbox_call(
    monkeypatch, node_data_overrides
):
    calls = record_run_code(monkeypatch)
    node_data = make_node_data(next_error_node="error_node").model_copy(update=node_data_overrides)
    subgraph, redis_service = build_subgraph_with_redis(node_data)

    result = await subgraph.ainvoke(make_state())

    assert calls == []
    error_details = [
        message["details"]
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    ]
    assert error_details == [
        "Variable path 'variables.__class__.status' is not allowed: path segments cannot start with '_'."
    ]
    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"


async def run_prompt_and_capture(monkeypatch, prompt_text: str, variables: dict):
    """Run one prompt row; return the prompt sent to the LLM and the published messages."""
    monkeypatch.setattr(RunPythonCodeService, "run_code", fake_run_code, raising=True)
    prompt_config = PromptConfigData(
        prompt_text=prompt_text, llm_data=make_llm_data(), result_variable="classification_result"
    )
    groups = [
        ClassificationConditionGroupData(
            group_name="prompt_row",
            expression="True",
            prompt_id="classify",
            next_node="after_prompt",
            order=0,
        ),
    ]
    subgraph, redis_service = build_subgraph_with_redis(
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
        await subgraph.ainvoke(make_state(variables))

    (llm_message,) = mock_completion.call_args.kwargs["messages"]
    return llm_message["content"], published_messages(redis_service)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt_text", "expected_prompt"),
    [
        ("Classify {text}", "Classify hello"),
        ("Classify {user}", "Classify {'name': 'Ann'}"),
        ("Classify {text} as {label}", "Classify {text} as {label}"),
        ('Classify {text}. Reply {{"label": "x"}}', 'Classify hello. Reply {"label": "x"}'),
        ('Classify {text}. Reply {"label": "x"}', 'Classify {text}. Reply {"label": "x"}'),
        ("Classify {user.name}", "Classify {user.name}"),
        ("Classify {text[0]}", "Classify {text[0]}"),
        ("Classify { brace {text}", "Classify { brace {text}"),
    ],
    ids=[
        "plain",
        "nested-value",
        "missing-variable-sends-prompt-as-written",
        "escaped-braces",
        "json-example-sends-prompt-as-written",
        "attribute-placeholder-not-followed",
        "index-placeholder-not-followed",
        "lone-brace-sends-prompt-as-written",
    ],
)
async def test_prompt_is_rendered_from_flow_variables(monkeypatch, prompt_text, expected_prompt):
    sent_prompt, messages = await run_prompt_and_capture(
        monkeypatch, prompt_text, {"text": "hello", "user": {"name": "Ann"}}
    )

    assert sent_prompt == expected_prompt
    (prompt_message,) = [
        message for message in messages if message["message_type"] == "classification_prompt"
    ]
    assert prompt_message["prompt_text"] == expected_prompt


@pytest.mark.asyncio
async def test_prompt_placeholder_cannot_read_the_crew_environment(monkeypatch):
    canary_value = "canary-from-the-crew-environment"
    monkeypatch.setenv("CDT_PROMPT_TEST_CANARY", canary_value)
    prompt_text = (
        "Classify {obj.update.__globals__[ast].sys.modules[os].environ[CDT_PROMPT_TEST_CANARY]}"
    )

    sent_prompt, messages = await run_prompt_and_capture(
        monkeypatch, prompt_text, {"obj": {"k": "v"}}
    )

    assert sent_prompt == prompt_text
    assert canary_value not in json.dumps(messages)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt_text", "expected_warnings"),
    [
        ("Classify {text}", []),
        (
            "Classify {user.name}",
            [
                "Classification node 'cdt_node' prompt sent as written, no placeholder filled: "
                "placeholder 'user.name' is not a plain variable name"
            ],
        ),
        (
            "Classify {text!r}",
            [
                "Classification node 'cdt_node' prompt sent as written, no placeholder filled: "
                "placeholder 'text' uses a conversion or format spec"
            ],
        ),
    ],
    ids=["rendered-no-warning", "dotted-placeholder", "conversion"],
)
async def test_prompt_sent_unrendered_leaves_a_warning(monkeypatch, prompt_text, expected_warnings):
    lines: list[str] = []
    sink_id = logger.add(lines.append, level="WARNING", format="{message}")
    try:
        await run_prompt_and_capture(monkeypatch, prompt_text, {"text": "hello", "user": {"name": "Ann"}})
    finally:
        logger.remove(sink_id)

    assert [line.strip() for line in lines if "prompt sent as written" in line] == expected_warnings
