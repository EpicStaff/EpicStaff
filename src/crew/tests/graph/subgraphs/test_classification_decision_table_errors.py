"""The errors ClassificationDecisionTableNodeSubgraph shows the user, word for word.

Code runs through the sandbox's own code wrapper (`run_in_sandbox_wrapper`), so line
numbers and messages are the ones the sandbox really reports for the code the node
generates. Failures of the sandbox service itself are the results `RunPythonCodeService`
makes up for them. LLM calls are replaced with litellm's own exception classes.
"""

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest
from dotdict import DotDict
from langgraph.graph import StateGraph
from loguru import logger

from models.state import State
from services.graph.events import StopEvent
from services.graph.exceptions import NodeExecutionError, StopSession
from services.run_python_code_service import (
    CORRELATION_ID_KEY,
    TIMEOUT_RETURNCODE,
    TIMEOUT_STDERR_MESSAGE,
    RunPythonCodeService,
)
from src.crew.services.graph.subgraphs.classification_decision_table_node import (
    ClassificationDecisionTableNodeSubgraph,
)
from src.crew.tests.graph.subgraphs.sandbox_wrapper_runner import run_in_sandbox_wrapper
from src.shared.models import PythonCodeData
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.models.graph_nodes import (
    ClassificationConditionGroupData,
    ClassificationDecisionTableNodeData,
    PromptConfigData,
)
from utils.singleton_meta import SingletonMeta

SANDBOX_REFERENCE = "0123456789ab"
UNREADABLE_RESULT_DATA = "not json: sk-live-abcdef"
PROVIDER_TEXT = "Incorrect API key provided: sk-live-abcdef"
_REFERENCE = r"[0-9a-f]{12}"

PRE_CODE = "def main():\n    x = 1\n    return total\n"
POST_CODE = "def main():\n    y = 2\n    return grand_total\n"
PRE_OK_CODE = "def main():\n    return 'pre'\n"
POST_OK_CODE = "def main():\n    return 'post'\n"


@pytest.fixture(autouse=True)
def reset_singleton():
    SingletonMeta._instances.pop(RunPythonCodeService, None)
    yield
    SingletonMeta._instances.pop(RunPythonCodeService, None)


def use_sandbox(monkeypatch, fail_when=None, failure: dict | None = None) -> None:
    """Run every code through the sandbox wrapper; calls `fail_when` picks get `failure`."""

    async def run_code(self, python_code_data, inputs, *args, **kwargs):
        if fail_when is not None and fail_when(python_code_data, inputs):
            return {"execution_id": "test", "stdout": "", **failure}
        return run_in_sandbox_wrapper(python_code_data.code, python_code_data.entrypoint, inputs)

    monkeypatch.setattr(RunPythonCodeService, "run_code", run_code, raising=True)


def row(expression: str | None = "True", **fields) -> ClassificationConditionGroupData:
    return ClassificationConditionGroupData(
        group_name="High score", expression=expression, next_node="node_A", **fields
    )


def node_data(*groups, next_error_node: str | None = "error_node", **fields):
    return ClassificationDecisionTableNodeData(
        node_name="cdt_node",
        condition_groups=list(groups),
        next_error_node=next_error_node,
        **fields,
    )


def make_state(variables: dict | None = None) -> State:
    return {
        "state_history": [],
        "variables": DotDict(variables or {}),
        "system_variables": {"nodes": {}, "execution_order": 0},
        "execution_counts": {},
    }


def build(data: ClassificationDecisionTableNodeData):
    redis_service = MagicMock()
    redis_service.aadd_graph_message = AsyncMock()
    subgraph = ClassificationDecisionTableNodeSubgraph(
        session_id=1,
        node_data=data,
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


def error_details(redis_service: MagicMock) -> list[str]:
    return [
        message["details"]
        for message in published_messages(redis_service)
        if message["message_type"] == "error"
    ]


async def run(data, variables: dict | None = None):
    subgraph, redis_service = build(data)
    result = await subgraph.ainvoke(make_state(variables))
    return result, error_details(redis_service)


# ---------------------------------------------------------------------------
# The user's code failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "expected_error"),
    [
        pytest.param(
            node_data(row("scroe > 1")),
            "Condition \"High score\": name 'scroe' is not defined",
            id="expression-name-error",
        ),
        pytest.param(
            node_data(row("score >")),
            'Condition "High score": invalid syntax',
            id="expression-syntax-error",
        ),
        pytest.param(
            node_data(row("score")),
            'Condition "High score" must give true or false.',
            id="expression-not-boolean",
        ),
        pytest.param(
            node_data(row(field_expressions={"score": "> limit"})),
            "Condition \"High score\": name 'limit' is not defined",
            id="field-expression-error",
        ),
        pytest.param(
            node_data(
                row(
                    field_manipulations={"bonus": "1"},
                    manipulation="a = 1\nb = 2\nvariables.total = total",
                )
            ),
            "Condition \"High score\", manipulation code: NameError on line 3: "
            "name 'total' is not defined",
            id="manipulation-keeps-the-users-line-numbers",
        ),
        pytest.param(
            node_data(row(manipulation='raise ValueError("a\\nb")')),
            'Condition "High score", manipulation code: ValueError on line 1: a\nb',
            id="manipulation-multi-line-message",
        ),
        pytest.param(
            node_data(
                row(
                    manipulation="import sys\n"
                    "print('ValueError on line 9: printed', file=sys.stderr)\n"
                    'raise ValueError("a\\nb")'
                )
            ),
            'Condition "High score", manipulation code: ValueError on line 3: a\nb',
            id="manipulation-leaves-out-what-the-code-printed",
        ),
        pytest.param(
            node_data(row("exit()")),
            'Condition "High score" stopped the code with exit().',
            id="expression-exit",
        ),
        pytest.param(
            node_data(row(field_manipulations={"variables.score": "scroe + 1"})),
            "Condition \"High score\", manipulation of \"score\": name 'scroe' is not defined",
            id="field-manipulation",
        ),
        pytest.param(
            node_data(row(), pre_python_code=PythonCodeData(code=PRE_CODE, entrypoint="main")),
            "Pre-computation code: NameError on line 3: name 'total' is not defined",
            id="pre-computation",
        ),
        pytest.param(
            node_data(row(), post_python_code=PythonCodeData(code=POST_CODE, entrypoint="main")),
            "Post-computation code: NameError on line 3: name 'grand_total' is not defined",
            id="post-computation",
        ),
    ],
)
async def test_user_code_error(monkeypatch, data, expected_error):
    use_sandbox(monkeypatch)

    result, errors = await run(data, {"score": 5})

    assert errors == [expected_error]
    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"


# ---------------------------------------------------------------------------
# The sandbox couldn't run the code
# ---------------------------------------------------------------------------

_SANDBOX_UNAVAILABLE = {
    "returncode": 1,
    "stderr": f"Node execution failed (reference: {SANDBOX_REFERENCE})",
    "result_data": None,
    CORRELATION_ID_KEY: SANDBOX_REFERENCE,
}
_RESULT_TIMED_OUT = {
    "returncode": TIMEOUT_RETURNCODE,
    "stderr": TIMEOUT_STDERR_MESSAGE,
    "result_data": None,
}
_UNREADABLE_RESULT = {"returncode": 0, "stderr": "", "result_data": UNREADABLE_RESULT_DATA}


def _is_condition(code, inputs):
    return "expressions" in inputs


def _is_manipulation(code, inputs):
    return "_from_ns" in code.code


def _is_pre(code, inputs):
    return code.code == PRE_OK_CODE


def _is_post(code, inputs):
    return code.code == POST_OK_CODE


_FAILING_PARTS = [
    pytest.param(_is_condition, 'Condition "High score"', id="condition"),
    pytest.param(_is_manipulation, 'Condition "High score"', id="manipulation"),
    pytest.param(_is_pre, "Pre-computation code", id="pre-computation"),
    pytest.param(_is_post, "Post-computation code", id="post-computation"),
]


def _data_running_every_part() -> ClassificationDecisionTableNodeData:
    return node_data(
        row(manipulation="variables.ran = True"),
        pre_python_code=PythonCodeData(code=PRE_OK_CODE, entrypoint="main"),
        pre_output_variable_path="variables.pre",
        post_python_code=PythonCodeData(code=POST_OK_CODE, entrypoint="main"),
        post_output_variable_path="variables.post",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(("fail_when", "subject"), _FAILING_PARTS)
async def test_sandbox_unavailable_cites_the_sandbox_reference(monkeypatch, fail_when, subject):
    use_sandbox(monkeypatch, fail_when, _SANDBOX_UNAVAILABLE)

    _, errors = await run(_data_running_every_part())

    assert errors == [
        f"{subject}: the code couldn't run because of a server error. "
        f"Try again or contact your administrator (reference: {SANDBOX_REFERENCE})."
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("fail_when", "subject"), _FAILING_PARTS)
async def test_result_that_never_arrived(monkeypatch, fail_when, subject):
    use_sandbox(monkeypatch, fail_when, _RESULT_TIMED_OUT)

    _, errors = await run(_data_running_every_part())

    assert errors == [
        f"{subject}: the code's result didn't arrive in time. "
        "Try again or contact your administrator."
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(("fail_when", "subject"), _FAILING_PARTS)
async def test_unreadable_result_cites_a_new_reference_and_logs_the_raw_result(
    monkeypatch, fail_when, subject
):
    use_sandbox(monkeypatch, fail_when, _UNREADABLE_RESULT)
    logged: list[str] = []
    sink_id = logger.add(logged.append, level="ERROR")
    try:
        _, errors = await run(_data_running_every_part())
    finally:
        logger.remove(sink_id)

    [details] = errors
    match = re.fullmatch(
        re.escape(f"{subject}: the code couldn't run because of a server error. ")
        + rf"Try again or contact your administrator \(reference: ({_REFERENCE})\)\.",
        details,
    )
    assert match is not None, details
    assert UNREADABLE_RESULT_DATA not in details
    assert any(UNREADABLE_RESULT_DATA in line and match.group(1) in line for line in logged)


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------


def prompt_data(prompt_text: str = "Classify {text}") -> ClassificationDecisionTableNodeData:
    return node_data(
        row(prompt_id="classify"),
        prompts={
            "classify": PromptConfigData(
                prompt_text=prompt_text,
                llm_data=LLMData(provider="openai", config=LLMConfigData(model="gpt-4o")),
            )
        },
    )


def llm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.usage.total_tokens = 1
    response.usage.prompt_tokens = 1
    response.usage.completion_tokens = 0
    response.choices = [MagicMock()]
    response.choices[0].message.content = content
    return response


@pytest.mark.asyncio
async def test_llm_error_of_a_known_kind_explains_it_without_the_provider_text(monkeypatch):
    use_sandbox(monkeypatch)
    logged: list[str] = []
    sink_id = logger.add(logged.append, level="DEBUG")
    try:
        with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
            completion.side_effect = litellm.AuthenticationError(
                message=PROVIDER_TEXT, llm_provider="openai", model="gpt-4o"
            )
            _, errors = await run(prompt_data(), {"text": "hi"})
    finally:
        logger.remove(sink_id)

    assert errors == [
        'Prompt "classify": The provider rejected the API key for model "gpt-4o". '
        "Check the key in the LLM settings."
    ]
    assert not any("sk-live-abcdef" in line for line in logged)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected_error"),
    [
        pytest.param(
            litellm.RateLimitError(message=PROVIDER_TEXT, llm_provider="openai", model="gpt-4o"),
            'Prompt "classify": The provider\'s rate limit for model "gpt-4o" was reached. '
            "Wait a minute and run the flow again.",
            id="rate-limit",
        ),
        pytest.param(
            litellm.ContextWindowExceededError(
                message=PROVIDER_TEXT, model="gpt-4o", llm_provider="openai"
            ),
            'Prompt "classify" is too long for model "gpt-4o". Shorten the prompt or its '
            "inputs, or choose a model with a bigger context window.",
            id="context-too-long",
        ),
        pytest.param(
            litellm.ContentPolicyViolationError(
                message=PROVIDER_TEXT, model="gpt-4o", llm_provider="openai"
            ),
            'Prompt "classify": The provider of model "gpt-4o" refused the request because '
            "of its content policy. Change the prompt or its inputs.",
            id="content-refused",
        ),
    ],
)
async def test_llm_error_that_the_prompt_can_fix_says_what_to_change_in_it(
    monkeypatch, error, expected_error
):
    use_sandbox(monkeypatch)

    with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
        completion.side_effect = error
        _, errors = await run(prompt_data(), {"text": "hi"})

    assert errors == [expected_error]


@pytest.mark.asyncio
async def test_prompt_without_an_llm_says_how_to_choose_one(monkeypatch):
    use_sandbox(monkeypatch)
    data = node_data(
        row(prompt_id="classify"),
        prompts={"classify": PromptConfigData(prompt_text="Classify {text}", llm_data=None)},
    )

    with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
        result, errors = await run(data, {"text": "hi"})

    assert errors == [
        'Prompt "classify" has no LLM. Choose one for it, or set a default LLM for the node.'
    ]
    assert not completion.called
    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"


@pytest.mark.asyncio
async def test_llm_error_of_an_unknown_kind_cites_a_reference_and_logs_only_its_class(
    monkeypatch,
):
    use_sandbox(monkeypatch)
    logged: list[str] = []
    sink_id = logger.add(logged.append, level="DEBUG")
    try:
        with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
            completion.side_effect = litellm.BadRequestError(
                message=PROVIDER_TEXT, model="gpt-4o", llm_provider="openai"
            )
            _, errors = await run(prompt_data(), {"text": "hi"})
    finally:
        logger.remove(sink_id)

    [details] = errors
    match = re.fullmatch(
        'Prompt "classify": The LLM request for model "gpt-4o" failed. '
        rf"Try again or contact your administrator \(reference: ({_REFERENCE})\)\.",
        details,
    )
    assert match is not None, details
    assert any("BadRequestError" in line and match.group(1) in line for line in logged)
    assert not any("sk-live-abcdef" in line for line in logged)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("prompt_text", "expected_error"),
    [
        pytest.param(
            "Classify { text",
            'Prompt "classify" has a "{" without a matching "}". '
            "To write a brace, double it: {{ or }}.",
            id="stray-opening-brace",
        ),
        pytest.param(
            "Classify {text} }",
            'Prompt "classify" has a "}" without a matching "{". '
            "To write a brace, double it: {{ or }}.",
            id="stray-closing-brace",
        ),
    ],
)
async def test_prompt_with_a_single_brace(monkeypatch, prompt_text, expected_error):
    use_sandbox(monkeypatch)

    with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
        result, errors = await run(prompt_data(prompt_text), {"text": "hi"})

    assert errors == [expected_error]
    assert not completion.called
    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"


@pytest.mark.asyncio
async def test_prompt_with_an_unknown_placeholder_is_sent_unrendered(monkeypatch):
    """Unchanged on purpose: existing flows rely on JSON braces passing through."""
    use_sandbox(monkeypatch)
    prompt_text = 'Classify {text} as {"label": "positive"}'

    with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
        completion.return_value = llm_response('{"label": "positive"}')
        result, errors = await run(prompt_data(prompt_text), {"text": "hi"})

    assert errors == []
    assert completion.call_args.kwargs["messages"][-1]["content"] == prompt_text
    assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "node_A"


# ---------------------------------------------------------------------------
# No error route, unexpected errors, stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "expected_message"),
    [
        pytest.param(
            node_data(row("scroe > 1"), next_error_node=None),
            "Condition \"High score\": name 'scroe' is not defined",
            id="condition",
        ),
        pytest.param(
            node_data(
                row(),
                next_error_node=None,
                pre_python_code=PythonCodeData(code=PRE_CODE, entrypoint="main"),
            ),
            "Pre-computation code: NameError on line 3: name 'total' is not defined",
            id="pre-computation",
        ),
        pytest.param(
            node_data(
                row(),
                next_error_node=None,
                post_python_code=PythonCodeData(code=POST_CODE, entrypoint="main"),
            ),
            "Post-computation code: NameError on line 3: name 'grand_total' is not defined",
            id="post-computation",
        ),
    ],
)
async def test_without_an_error_route_the_session_fails_with_the_shown_error(
    monkeypatch, data, expected_message
):
    use_sandbox(monkeypatch)
    subgraph, redis_service = build(data)

    with pytest.raises(NodeExecutionError) as raised:
        await subgraph.ainvoke(make_state())

    assert raised.value.public_message == expected_message
    assert raised.value.correlation_id is None
    assert error_details(redis_service) == [expected_message]


@pytest.mark.asyncio
async def test_without_an_error_route_a_sandbox_failure_fails_the_session_under_its_reference(
    monkeypatch,
):
    use_sandbox(monkeypatch, _is_condition, _SANDBOX_UNAVAILABLE)
    subgraph, _ = build(node_data(row(), next_error_node=None))

    with pytest.raises(NodeExecutionError) as raised:
        await subgraph.ainvoke(make_state())

    assert raised.value.correlation_id == SANDBOX_REFERENCE


@pytest.mark.asyncio
@pytest.mark.parametrize("next_error_node", ["error_node", None])
async def test_unexpected_pre_computation_error_shows_a_reference(monkeypatch, next_error_node):
    sensitive_text = "sk-live-abcdef at https://internal.epicstaff.local"

    async def run_code(self, *args, **kwargs):
        raise RuntimeError(sensitive_text)

    monkeypatch.setattr(RunPythonCodeService, "run_code", run_code, raising=True)
    subgraph, redis_service = build(
        node_data(
            row(),
            next_error_node=next_error_node,
            pre_python_code=PythonCodeData(code=PRE_OK_CODE, entrypoint="main"),
        )
    )
    logged: list[str] = []
    sink_id = logger.add(logged.append, level="ERROR")
    try:
        if next_error_node is None:
            with pytest.raises(NodeExecutionError):
                await subgraph.ainvoke(make_state())
        else:
            result = await subgraph.ainvoke(make_state())
            assert result["system_variables"]["nodes"]["cdt_node"]["result_node"] == "error_node"
    finally:
        logger.remove(sink_id)

    [details] = error_details(redis_service)
    match = re.fullmatch(rf"Node execution failed \(reference: ({_REFERENCE})\)", details)
    assert match is not None, details
    assert any(sensitive_text in line and match.group(1) in line for line in logged)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data",
    [
        pytest.param(node_data(row()), id="condition"),
        pytest.param(
            node_data(row(), pre_python_code=PythonCodeData(code=PRE_OK_CODE, entrypoint="main")),
            id="pre-computation",
        ),
    ],
)
async def test_stop_is_not_reported_as_a_node_error(monkeypatch, data):
    async def run_code(self, *args, **kwargs):
        raise StopSession()

    monkeypatch.setattr(RunPythonCodeService, "run_code", run_code, raising=True)
    subgraph, redis_service = build(data)

    with pytest.raises(StopSession):
        await subgraph.ainvoke(make_state())

    assert error_details(redis_service) == []
