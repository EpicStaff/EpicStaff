"""End-to-end happy-path test for DynamicVenvExecutorChain.

The test drives the real chain (DummyHandler → CreateVenvHandler →
InstallLibrariesHandler → ExecuteCodeHandler) without any real venv, pip, or
network access.  OS boundaries are mocked at the asyncio subprocess level,
following the same pattern used in test_build_environment_handler.py and
test_execute_code_handler_storage.py.

Design notes
------------
- create_subprocess_shell (CreateVenvHandler):
    The handler calls this only when venv_path doesn't exist yet.  After the
    "real" call the venv directory would be created by the venv tool; our fake
    must create that directory itself so that subsequent stages find it.  The
    command string has the form ``<interpreter> -m venv <venv_path>``, so we
    extract the last token to learn the path.

- create_subprocess_exec (InstallLibrariesHandler + ExecuteCodeHandler):
    InstallLibrariesHandler fires several exec calls (pip upgrade, pip freeze,
    pip install × N).  ExecuteCodeHandler fires one exec call for the user
    script.  We distinguish the "user script" call from pip calls by checking
    whether the last positional arg ends with "code.py" (the temp_code_path
    written by ExecuteCodeHandler).  Only for that call do we pre-write the
    result JSON to output.txt; all other calls just return returncode 0 with
    empty stdio.
"""

import json
from pathlib import Path
from unittest.mock import Mock

import pytest

import dynamic_venv_executor_chain
from dynamic_venv_executor_chain import DynamicVenvExecutorChain


class _FakeProcess:
    """Minimal asyncio.subprocess.Process look-alike that always succeeds."""

    returncode = 0

    async def communicate(self):
        return (b"", b"")


def _make_fake_shell(recorded_shell_calls: list):
    """Return an async fake for asyncio.create_subprocess_shell.

    Side-effect: creates the venv_path directory so that InstallLibrariesHandler
    finds an existing venv to work against.  The path is the last whitespace-
    separated token of the shell command string, matching the pattern::

        <interpreter> -m venv <venv_path>
    """

    async def _fake_shell(cmd: str, **kwargs):
        recorded_shell_calls.append(cmd)
        # Extract venv_path from the command string and create the directory.
        venv_path_str = cmd.strip().split()[-1]
        Path(venv_path_str).mkdir(parents=True, exist_ok=True)
        return _FakeProcess()

    return _fake_shell


def _make_fake_exec(result_file_path: Path, expected_result: object, recorded_exec_calls: list):
    """Return an async fake for asyncio.create_subprocess_exec.

    Distinguishes the "run user code" call from pip calls by checking whether
    the last positional arg ends with "code.py".  For the code-run call it
    pre-writes result_file_path with the JSON-serialised expected_result so
    ExecuteCodeHandler can read it back.
    """

    async def _fake_exec(*args, **kwargs):
        recorded_exec_calls.append(args)
        # args[0] is the python executable; args[-1] is the last positional
        # argument (either a pip subcommand token or the code file path).
        last_arg = str(args[-1]) if args else ""
        if last_arg.endswith("code.py"):
            result_file_path.write_text(json.dumps(expected_result), encoding="utf-8")
        return _FakeProcess()

    return _fake_exec


@pytest.mark.asyncio
async def test_chain_happy_path_returns_code_result_data(tmp_path, monkeypatch):
    """DynamicVenvExecutorChain.run() traverses all handlers and returns success.

    Assertions:
    - Returns an object with returncode == 0.
    - execution_id matches the value passed to run().
    - result_data matches the JSON pre-written by the fake exec subprocess.
    - At least one shell call was made (venv creation).
    - At least one exec call was made (code execution).
    - No real venv, pip, or network is involved.
    """
    output_path = tmp_path / "output"
    base_venv_path = tmp_path / "venvs"
    output_path.mkdir()
    base_venv_path.mkdir()

    execution_id = "test-chain-exec-001"
    expected_result = {"answer": 42}

    # result_file_path is computed inside run() as output_path / execution_id / "output.txt"
    result_file_path = output_path / execution_id / "output.txt"

    recorded_shell_calls: list = []
    recorded_exec_calls: list = []

    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_shell",
        _make_fake_shell(recorded_shell_calls),
    )
    monkeypatch.setattr(
        dynamic_venv_executor_chain.asyncio,
        "create_subprocess_exec",
        _make_fake_exec(result_file_path, expected_result, recorded_exec_calls),
    )

    storage_credential_manager = Mock(spec=["build_policy", "create", "revoke"])

    chain = DynamicVenvExecutorChain(
        output_path=output_path,
        base_venv_path=base_venv_path,
        storage_credential_manager=storage_credential_manager,
    )

    result = await chain.run(
        libraries=[],
        venv_name="test-venv",
        execution_id=execution_id,
        code="def main(**kwargs):\n    return {'answer': 42}",
        entrypoint="main",
        func_kwargs={},
        global_kwargs={},
        use_storage=False,
    )

    assert result.returncode == 0, f"Expected returncode 0, got {result.returncode!r} (stderr={result.stderr!r})"
    assert result.execution_id == execution_id
    assert result.result_data == json.dumps(expected_result)
    assert len(recorded_shell_calls) >= 1, "Expected at least one create_subprocess_shell call (venv creation)"
    assert len(recorded_exec_calls) >= 1, "Expected at least one create_subprocess_exec call (code execution)"
    storage_credential_manager.build_policy.assert_not_called()
    storage_credential_manager.create.assert_not_called()
    storage_credential_manager.revoke.assert_not_called()
