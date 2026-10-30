"""
PythonCodeToolExecutor: turns an LLM tool call into a sandbox CodeTask and the
sandbox result into a ToolResult. The sandbox service is replaced by a fake that
records the task it receives.
"""

from __future__ import annotations

import pytest

from app.tools.executors.python_code import PythonCodeToolExecutor
from shared.models.storage_scope import StorageCredentials
from shared.models.tools import (
    ArgsSchema,
    CodeResultData,
    PythonCodeData,
    PythonCodeToolData,
)


def _make_tool_data(**overrides) -> PythonCodeToolData:
    code_defaults = dict(
        venv_id=42,
        code="def run(x): return x",
        entrypoint="run",
        global_kwargs=None,
        use_storage=False,
    )
    python_code = PythonCodeData(**{**code_defaults, **overrides.pop("python_code_overrides", {})})
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


class FakeSandbox:
    def __init__(self, result: CodeResultData | Exception):
        self.result = result
        self.tasks = []

    async def submit(self, task):
        self.tasks.append(task)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


CREDENTIALS = StorageCredentials(access_key="test-access", secret_key="test-secret")


@pytest.mark.parametrize(
    ("python_code_overrides", "credentials", "expected_task"),
    [
        pytest.param(
            {}, None,
            {"venv_id": 42, "code": "def run(x): return x",
             "entrypoint": "run", "func_kwargs": {"x": "hello"}, "global_kwargs": None, "use_storage": False,
             "storage_allowed_paths": None, "storage_org_prefix": None, "session_id": None, "org_id": None},
            id="defaults-and-llm-args-only",
        ),
        pytest.param(
            {"use_storage": True, "storage_allowed_paths": ["reports/"], "storage_org_prefix": "org1",
             "session_id": 42, "org_id": 77},
            CREDENTIALS,
            {"use_storage": True, "storage_allowed_paths": ["reports/"], "storage_org_prefix": "org1",
             "session_id": 42, "storage_credentials": CREDENTIALS},
            id="storage-scope",
        ),
        # get_secret() in the sandbox sees only what the tool declared.
        pytest.param({"secrets": {"MY_SECRET": "sk-live-12345"}}, None, {"secrets": {"MY_SECRET": "sk-live-12345"}}, id="secrets"),
        pytest.param({"global_kwargs": {"mode": "production"}}, None, {"global_kwargs": {"mode": "production"}, "org_id": None}, id="global-kwargs-no-org"),
        # The graph's org_id is authoritative over an author-editable global of the same name.
        pytest.param(
            {"org_id": 77, "global_kwargs": {"org_id": 999, "mode": "production"}}, None,
            {"global_kwargs": {"org_id": 77, "mode": "production"}, "org_id": 77},
            id="org-id-wins-over-global",
        ),
        pytest.param({"org_id": 77}, None, {"global_kwargs": {"org_id": 77}, "org_id": 77}, id="org-id-injected"),
        # Tools read `session_id` from globals() (e.g. fanout_tool's recursion guard).
        pytest.param({"session_id": 42}, None, {"global_kwargs": {"session_id": 42}, "session_id": 42}, id="session-id-injected"),
        pytest.param(
            {"session_id": 42, "global_kwargs": {"session_id": 999, "mode": "production"}}, None,
            {"global_kwargs": {"session_id": 42, "mode": "production"}, "session_id": 42},
            id="session-id-wins-over-global",
        ),
        pytest.param(
            {"global_kwargs": {"session_id": 999}}, None,
            {"global_kwargs": {"session_id": 999}, "session_id": None},
            id="no-typed-session-id-leaves-global-untouched",
        ),
        pytest.param(
            {"session_id": 42, "org_id": 77}, None,
            {"global_kwargs": {"session_id": 42, "org_id": 77}},
            id="session-id-and-org-id-both-injected",
        ),
        # The sandbox enforces the tool's own timeout instead of its default.
        pytest.param({"execution_timeout": 42}, None, {"execution_timeout": 42}, id="execution-timeout"),
    ],
)
async def test_sandbox_task_carries_the_tool_configuration(python_code_overrides, credentials, expected_task):
    sandbox = FakeSandbox(_make_success_result())
    data = _make_tool_data(python_code_overrides=python_code_overrides)
    configured_globals = data.python_code.global_kwargs

    await PythonCodeToolExecutor(sandbox, data, storage_credentials=credentials)({"x": "hello"})

    (task,) = sandbox.tasks
    assert {field: getattr(task, field) for field in expected_task} == expected_task
    # The tool's own configuration is never mutated by the org_id override.
    assert data.python_code.global_kwargs == configured_globals


@pytest.mark.parametrize(
    ("sandbox_result", "expected_content", "expected_error"),
    [
        (_make_success_result(result_data="the answer"), "the answer", False),
        (_make_error_result(stderr="NameError: undefined"), "NameError: undefined", True),
        (
            CodeResultData(execution_id="exec-1", result_data=None, stderr="", stdout="partial output", returncode=1),
            "partial output", True,
        ),
        (ConnectionError("Redis gone"), "Sandbox transport error: Redis gone", True),
    ],
    ids=["success", "stderr", "nonzero-uses-stdout", "transport-error"],
)
async def test_sandbox_result_becomes_the_tool_result(sandbox_result, expected_content, expected_error):
    result = await PythonCodeToolExecutor(FakeSandbox(sandbox_result), _make_tool_data())({})

    assert (result.content, result.is_error) == (expected_content, expected_error)


async def test_invalid_storage_scope_returns_fixed_error_without_secrets():
    """pydantic's ValidationError repr embeds `input_value` -- the whole dict
    handed to CodeTaskData, carrying `secrets` plaintext and
    `storage_credentials.secret_key`. ToolResult.content goes straight into the
    LLM transcript, so it must carry none of it."""
    secret_value = "sk-live-SUPERSECRET-0123456789"
    storage_secret_key = "SK-MINIO-SUPERSECRET-9876543210"

    sandbox = FakeSandbox(_make_success_result())

    data = _make_tool_data(
        python_code_overrides={
            "use_storage": True,
            "storage_org_prefix": None,
            "org_id": None,
            "secrets": {"MY_SECRET": secret_value},
        }
    )
    executor = PythonCodeToolExecutor(
        sandbox,
        data,
        storage_credentials=StorageCredentials(
            access_key="AK-PUBLIC", secret_key=storage_secret_key
        ),
    )
    result = await executor({})

    assert result.is_error is True
    assert result.content == "Invalid storage scope for code execution."
    for forbidden in (secret_value, storage_secret_key, "MY_SECRET", "input_value"):
        assert forbidden not in result.content
    assert sandbox.tasks == []
