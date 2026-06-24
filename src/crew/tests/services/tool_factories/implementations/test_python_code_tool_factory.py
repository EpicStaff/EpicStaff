import asyncio
import threading
from typing import Any

import pytest
from crewai.tools.base_tool import Tool

from services.crew.tool_factories import PythonCodeToolFactory
from services.graph.events import StopEvent
from src.shared.models import PythonCodeToolData, PythonCodeData


def make_data(
    name: str = "tool",
    description: str = "description",
    variables: list[dict] | None = None,
    python_code_global_kwargs: dict | None = None,
) -> PythonCodeToolData:
    return PythonCodeToolData(
        id=1,
        name=name,
        description=description,
        variables=variables or [],
        python_code=PythonCodeData(
            venv_name="venv",
            code="def main(**kw): return kw",
            entrypoint="main",
            libraries=[],
            global_kwargs=python_code_global_kwargs,
        ),
    )


class FakeRunPythonCodeService:
    """
    Fake services.run_python_code_service.RunPythonCodeService
    """

    def __init__(self, result=None):
        self.result = result or {"returncode": 0, "result_data": "ok", "stderr": ""}
        self.calls = []

    async def run_code(self, **kwargs) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.result


@pytest.fixture
def fake_executor() -> FakeRunPythonCodeService:
    return FakeRunPythonCodeService()


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=loop.run_forever, daemon=True)
    thread.start()
    yield loop
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=2)
    loop.close()


@pytest.fixture
def stop_event() -> StopEvent:
    return StopEvent()


def test_create_returns_tool_instance(fake_executor, loop, stop_event):
    factory = PythonCodeToolFactory(executor=fake_executor, asyncio_loop=loop)

    tool = factory.create(data=make_data(), global_kwargs={}, stop_event=stop_event)

    assert isinstance(tool, Tool)


@pytest.mark.parametrize(
    "result_dict,expected",
    [
        ({"returncode": 0, "result_data": "ok", "stderr": ""}, "ok"),
        ({"returncode": 1, "result_data": "", "stderr": "error"}, "error"),
    ],
)
def test_run_returns_result_based_on_returncode(
    fake_executor,
    loop,
    stop_event,
    result_dict,
    expected,
):
    fake_executor.result = result_dict
    factory = PythonCodeToolFactory(executor=fake_executor, asyncio_loop=loop)
    tool = factory.create(data=make_data(), global_kwargs={}, stop_event=stop_event)

    assert tool.func() == expected


@pytest.mark.parametrize(
    "python_code_global_kwargs,run_func_kwargs,expected_inputs",
    [
        ({"a": 1}, {"b": 2}, {"a": 1, "b": 2}),
        ({"a": 1}, {"a": 99}, {"a": 99}),
        (None, {"x": 1}, {"x": 1}),
        ({}, {"x": 1}, {"x": 1}),
        ({"a": 1}, {}, {"a": 1}),
    ],
    ids=[
        "merge",
        "overwrite_global_kwargs",
        "global_kwargs_is_None",
        "global_kwargs_is_empty",
        "run_func_kwargs_is_empty",
    ],
)
def test_run_merges_global_kwargs_with_call_kwargs(
    fake_executor,
    loop,
    stop_event,
    python_code_global_kwargs,
    run_func_kwargs,
    expected_inputs,
):
    factory = PythonCodeToolFactory(executor=fake_executor, asyncio_loop=loop)
    data = make_data(python_code_global_kwargs=python_code_global_kwargs)
    tool = factory.create(data=data, global_kwargs={}, stop_event=stop_event)

    tool.func(**run_func_kwargs)

    assert len(fake_executor.calls) == 1
    assert fake_executor.calls[0]["inputs"] == expected_inputs


def test_run_passes_executor_arguments(fake_executor, loop, stop_event):
    factory = PythonCodeToolFactory(executor=fake_executor, asyncio_loop=loop)
    data = make_data()
    global_kwargs = {"trace_id": "abc"}

    tool = factory.create(data=data, global_kwargs=global_kwargs, stop_event=stop_event)
    tool.func()

    call = fake_executor.calls[0]
    assert call["python_code_data"] is data.python_code
    assert call["additional_global_kwargs"] is global_kwargs
    assert call["stop_event"] is stop_event


def test_factory_uses_provided_event_loop(fake_executor):
    custom_loop = asyncio.new_event_loop()
    try:
        factory = PythonCodeToolFactory(
            executor=fake_executor, asyncio_loop=custom_loop
        )
        assert factory.asyncio_loop is custom_loop
    finally:
        custom_loop.close()


def test_factory_falls_back_to_get_event_loop_when_not_provided(fake_executor):
    expected_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(expected_loop)
    try:
        factory = PythonCodeToolFactory(executor=fake_executor)
        assert factory.asyncio_loop is expected_loop
    finally:
        asyncio.set_event_loop(None)
        expected_loop.close()
