"""
A run whose request key crew deleted (the user stopped the session) ends
quietly: no further LLM or tool calls, nothing more published, message acked.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable

from app import data_loader
from app.data_loader import DataLoader
from app.enums import RunType
from app.factory import RunnerFactory
from app.llm.client import LLMChunk, LLMClient, ToolCallFragment
from app.loop.agent_loop import DefaultAgentLoop
from app.request_handler import RequestHandler
from app.resources.resolver import AgentResolver
from app.runners.deps import RunnerDependencies
from app.runners.list_of_tasks import ListOfTasksRunner
from app.runners.single_task import SingleTaskRunner
from redis.exceptions import ConnectionError as RedisConnectionError
from shared.models.agent_service import AgentRequest
from shared.models.tools import CodeResultData, CodeTaskData
from shared.redis_streams import StreamEnvelope

REQUEST_KEY = "agent:request:run-a"


class FakeKeyValueRedis:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def exists(self, *keys: str) -> int:
        return sum(key in self.values for key in keys)

    async def aclose(self) -> None:
        pass


class RecordingStreamClient:
    def __init__(self) -> None:
        self.published_types: list[str] = []
        self.acked: list[str] = []

    async def publish(self, stream, fields, maxlen=1_000_000, approximate=True, ttl_s=None):
        self.published_types.append(fields["type"])

    async def ack(self, stream, group, *message_ids):
        self.acked.extend(message_ids)
        return len(message_ids)


class ScriptedLLM(LLMClient):
    """Pops one ``(before_reply, chunks)`` step per call; ``before_reply`` may be None."""

    def __init__(self, steps: list[tuple[Callable[[], None] | None, list[LLMChunk]]]) -> None:
        self._steps = steps
        self.calls = 0

    async def _iterate(self, chunks: list[LLMChunk]) -> AsyncIterator[LLMChunk]:
        for chunk in chunks:
            yield chunk

    def chat(self, messages, tools, model_config, *, stream, runtime_config=None):
        self.calls += 1
        before_reply, chunks = self._steps.pop(0)
        if before_reply is not None:
            before_reply()
        return self._iterate(chunks)


class FakeSandbox:
    def __init__(self, on_submit: Callable[[], None] | None = None, returncode: int = 0) -> None:
        self.submitted = 0
        self._on_submit = on_submit
        self._returncode = returncode

    async def submit(self, task: CodeTaskData, *, timeout: float | None = None) -> CodeResultData:
        self.submitted += 1
        if self._on_submit is not None:
            self._on_submit()
        return CodeResultData(
            execution_id=task.execution_id,
            result_data="42",
            stderr="" if self._returncode == 0 else "boom",
            stdout="",
            returncode=self._returncode,
        )


def _tool_call(call_id: str) -> list[LLMChunk]:
    return [
        LLMChunk(
            tool_call_fragment=ToolCallFragment(id=call_id, name="lookup", arguments_delta="{}")
        ),
        LLMChunk(finish_reason="tool_calls"),
    ]


def _two_tool_calls() -> list[LLMChunk]:
    return _tool_call("c1")[:1] + _tool_call("c2")


def _text(text: str) -> list[LLMChunk]:
    return [LLMChunk(delta_text=text), LLMChunk(finish_reason="stop")]


def _request_blob(run_type: RunType, **agent_overrides) -> str:
    payload = (
        {"task_instructions": "Look it up."}
        if run_type == RunType.SINGLE_TASK
        else {
            "tasks": [
                {"name": "first", "instructions": "Look it up."},
                {"name": "second", "instructions": "Summarize."},
            ]
        }
    )
    request = AgentRequest(
        correlation_id="ignored",
        run_type=run_type,
        agents=[
            {
                "id": 1,
                "name": "researcher",
                "role": "Researcher",
                "instructions": "Research.",
                "llm": {"provider": "openai", "config": {"model": "gpt-4o"}},
                "tool_refs": ["python-code-tool:1"],
                **agent_overrides,
            }
        ],
        tools=[
            {
                "unique_name": "python-code-tool:1",
                "data": {
                    "id": 1,
                    "name": "lookup",
                    "description": "Looks things up.",
                    "args_schema": {"type": "object", "properties": {}},
                    "python_code": {
                        "venv_name": "venv_1",
                        "code": "def run(): return 42",
                        "entrypoint": "run",
                        "libraries": [],
                    },
                },
            }
        ],
        payload=payload,
    )
    return json.dumps(request.model_dump(exclude={"correlation_id"}))


async def _run(monkeypatch, run_type: RunType, llm: ScriptedLLM, sandbox: FakeSandbox, store):
    async def from_url(url, **kwargs):
        return store

    monkeypatch.setattr(data_loader.aioredis, "from_url", from_url)
    loader = DataLoader(host="localhost", port=6379)
    await loader.connect()

    factory = RunnerFactory(
        RunnerDependencies(
            resolver=AgentResolver(sandbox, mcp_gateway=None),
            loop=DefaultAgentLoop(llm),
        )
    )
    factory.register(RunType.SINGLE_TASK, SingleTaskRunner)
    factory.register(RunType.LIST_OF_TASKS, ListOfTasksRunner)
    stream_client = RecordingStreamClient()
    handler = RequestHandler(
        loader=loader,
        factory=factory,
        redis_client=stream_client,
        result_stream_prefix="agent.results",
        result_stream_ttl_s=3600,
        request_stream="agent.requests",
        consumer_group="agent-executors",
    )
    envelope = StreamEnvelope(
        type="agent.run", correlation_id="run-a", payload={"request_key": REQUEST_KEY}
    )

    await handler.handle(envelope, message_id="1-0", stream="agent.requests")
    return stream_client


async def test_run_whose_request_key_stays_present_completes(monkeypatch):
    store = FakeKeyValueRedis({REQUEST_KEY: _request_blob(RunType.SINGLE_TASK)})
    llm = ScriptedLLM([(None, _tool_call("c1")), (None, _text("done"))])
    sandbox = FakeSandbox()

    stream_client = await _run(monkeypatch, RunType.SINGLE_TASK, llm, sandbox, store)

    assert (llm.calls, sandbox.submitted) == (2, 1)
    assert stream_client.published_types == ["agent.tool_call", "agent.tool_result", "agent.result"]
    assert stream_client.acked == ["1-0"]


async def test_stop_during_a_tool_call_skips_the_next_llm_call_and_publishes_nothing_more(
    monkeypatch,
):
    store = FakeKeyValueRedis({REQUEST_KEY: _request_blob(RunType.SINGLE_TASK)})
    llm = ScriptedLLM([(None, _tool_call("c1")), (None, _text("done"))])
    sandbox = FakeSandbox(on_submit=lambda: store.values.pop(REQUEST_KEY))

    stream_client = await _run(monkeypatch, RunType.SINGLE_TASK, llm, sandbox, store)

    assert (llm.calls, sandbox.submitted) == (1, 1)
    assert stream_client.published_types == ["agent.tool_call", "agent.tool_result"]
    assert stream_client.acked == ["1-0"]


async def test_stop_during_an_llm_call_runs_none_of_its_tool_calls(monkeypatch):
    store = FakeKeyValueRedis({REQUEST_KEY: _request_blob(RunType.SINGLE_TASK)})
    llm = ScriptedLLM([(lambda: store.values.pop(REQUEST_KEY), _two_tool_calls())])
    sandbox = FakeSandbox()

    stream_client = await _run(monkeypatch, RunType.SINGLE_TASK, llm, sandbox, store)

    assert (llm.calls, sandbox.submitted) == (1, 0)
    assert stream_client.published_types == []
    assert stream_client.acked == ["1-0"]


async def test_stop_during_a_list_of_tasks_run_starts_no_further_task(monkeypatch):
    store = FakeKeyValueRedis({REQUEST_KEY: _request_blob(RunType.LIST_OF_TASKS)})
    llm = ScriptedLLM(
        [
            (lambda: store.values.pop(REQUEST_KEY), _text("first done")),
            (None, _text("second done")),
        ]
    )
    sandbox = FakeSandbox()

    stream_client = await _run(monkeypatch, RunType.LIST_OF_TASKS, llm, sandbox, store)

    assert llm.calls == 1
    assert "agent.result" not in stream_client.published_types
    assert "agent.error" not in stream_client.published_types
    assert stream_client.acked == ["1-0"]


async def test_stop_before_the_failure_limit_summary_skips_that_llm_call(monkeypatch):
    store = FakeKeyValueRedis(
        {REQUEST_KEY: _request_blob(RunType.SINGLE_TASK, max_consecutive_failures=1)}
    )
    llm = ScriptedLLM([(None, _tool_call("c1")), (None, _text("summary"))])
    sandbox = FakeSandbox(on_submit=lambda: store.values.pop(REQUEST_KEY), returncode=1)

    stream_client = await _run(monkeypatch, RunType.SINGLE_TASK, llm, sandbox, store)

    assert (llm.calls, sandbox.submitted) == (1, 1)
    assert stream_client.published_types == ["agent.tool_call", "agent.tool_result"]


class UnreachableExistsRedis(FakeKeyValueRedis):
    async def exists(self, *keys: str) -> int:
        raise RedisConnectionError("Connection closed by server.")


async def test_a_failing_withdrawal_check_lets_the_run_complete(monkeypatch):
    store = UnreachableExistsRedis({REQUEST_KEY: _request_blob(RunType.SINGLE_TASK)})
    llm = ScriptedLLM([(None, _tool_call("c1")), (None, _text("done"))])

    stream_client = await _run(monkeypatch, RunType.SINGLE_TASK, llm, FakeSandbox(), store)

    assert llm.calls == 2
    assert stream_client.published_types[-1] == "agent.result"
