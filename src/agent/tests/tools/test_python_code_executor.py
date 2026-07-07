"""
Tests for PythonCodeToolExecutor.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.tools.executors.python_code import PythonCodeToolExecutor
from shared.models.agent_service import ToolResult
from shared.models.tools import (
    ArgsSchema,
    CodeResultData,
    PythonCodeData,
    PythonCodeToolData,
)


def _make_tool_data(**overrides) -> PythonCodeToolData:
    code_defaults = dict(
        venv_name="venv_pyt_42",
        code="def run(x): return x",
        entrypoint="run",
        libraries=["requests"],
        global_kwargs=None,
        use_storage=False,
    )
    python_code = PythonCodeData(
        **{**code_defaults, **overrides.pop("python_code_overrides", {})}
    )
    return PythonCodeToolData(
        id=1,
        name=overrides.pop("name", "my_tool"),
        description=overrides.pop("description", "A test tool."),
        args_schema=ArgsSchema(
            properties={"x": {"type": "string"}},
        ),
        python_code=python_code,
        **overrides,
    )


def _make_success_result(
    execution_id: str = "exec-1", result_data: str = "output"
) -> CodeResultData:
    return CodeResultData(
        execution_id=execution_id,
        result_data=result_data,
        stderr="",
        stdout="",
        returncode=0,
    )


def _make_error_result(
    execution_id: str = "exec-1", stderr: str = "something went wrong"
) -> CodeResultData:
    return CodeResultData(
        execution_id=execution_id,
        result_data=None,
        stderr=stderr,
        stdout="",
        returncode=1,
    )


async def test_builds_code_task_data_with_correct_fields():
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(return_value=_make_success_result())

    data = _make_tool_data()
    executor = PythonCodeToolExecutor(sandbox, data)
    await executor({"x": "hello"})

    sandbox.submit.assert_called_once()
    task = sandbox.submit.call_args[0][0]

    assert task.venv_name == "venv_pyt_42"
    assert task.libraries == ["requests"]
    assert task.code == "def run(x): return x"
    assert task.entrypoint == "run"
    assert task.global_kwargs is None
    assert task.use_storage is False


async def test_func_kwargs_is_llm_args_only():
    """func_kwargs contains only the LLM-supplied args — no configuration merge."""
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(return_value=_make_success_result())

    data = _make_tool_data()
    executor = PythonCodeToolExecutor(sandbox, data)
    await executor({"mode": "override", "extra": "value"})

    task = sandbox.submit.call_args[0][0]
    assert task.func_kwargs == {"mode": "override", "extra": "value"}


async def test_success_returns_tool_result_with_content():
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(
        return_value=_make_success_result(result_data="the answer")
    )

    executor = PythonCodeToolExecutor(sandbox, _make_tool_data())
    result = await executor({})

    assert isinstance(result, ToolResult)
    assert result.content == "the answer"
    assert result.is_error is False


async def test_nonzero_returncode_returns_error_with_stderr():
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(
        return_value=_make_error_result(stderr="NameError: undefined")
    )

    executor = PythonCodeToolExecutor(sandbox, _make_tool_data())
    result = await executor({})

    assert result.is_error is True
    assert "NameError" in result.content


async def test_nonzero_returncode_with_empty_stderr_uses_stdout():
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(
        return_value=CodeResultData(
            execution_id="exec-1",
            result_data=None,
            stderr="",
            stdout="partial output",
            returncode=1,
        )
    )

    executor = PythonCodeToolExecutor(sandbox, _make_tool_data())
    result = await executor({})

    assert result.is_error is True
    assert "partial output" in result.content


async def test_sandbox_raises_returns_transport_error():
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(side_effect=ConnectionError("Redis gone"))

    executor = PythonCodeToolExecutor(sandbox, _make_tool_data())
    result = await executor({})

    assert result.is_error is True
    assert "Sandbox transport error" in result.content
    assert "Redis gone" in result.content


async def test_execution_id_is_unique_per_call():
    captured_ids: list[str] = []

    async def capturing_submit(task):
        captured_ids.append(task.execution_id)
        return _make_success_result(execution_id=task.execution_id)

    sandbox = MagicMock()
    sandbox.submit = capturing_submit

    executor = PythonCodeToolExecutor(sandbox, _make_tool_data())
    await executor({})
    await executor({})

    assert len(captured_ids) == 2
    assert captured_ids[0] != captured_ids[1]


async def test_storage_defaults_to_disabled():
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(return_value=_make_success_result())

    executor = PythonCodeToolExecutor(sandbox, _make_tool_data())
    await executor({})

    task = sandbox.submit.call_args[0][0]
    assert task.use_storage is False
    assert task.storage_allowed_paths is None
    assert task.storage_org_prefix is None
    assert task.session_id is None


async def test_storage_config_read_from_tool_data():
    sandbox = MagicMock()
    sandbox.submit = AsyncMock(return_value=_make_success_result())

    data = _make_tool_data(
        python_code_overrides={
            "use_storage": True,
            "storage_allowed_paths": ["reports/"],
            "storage_org_prefix": "org1",
            "session_id": 42,
        }
    )
    executor = PythonCodeToolExecutor(sandbox, data)
    await executor({})

    task = sandbox.submit.call_args[0][0]
    assert task.use_storage is True
    assert task.storage_allowed_paths == ["reports/"]
    assert task.storage_org_prefix == "org1"
    assert task.session_id == 42
