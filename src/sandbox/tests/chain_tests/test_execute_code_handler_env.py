"""Secret delivery, in both directions.

Inbound: secrets travel in the child process's environment, never in generated
source. wrap_code's output is written to temp_code_path on disk; the environment is
not. That distinction is the whole point of this delivery mechanism, so both halves
are asserted here.

Outbound: whatever the child emits is scrubbed of those same values before the
handler returns, so a value the child was given cannot leave it. Unit coverage of the
scrubbing itself lives in test_secret_scrubber.py; TestOutputStaysClean below drives
the real handler to prove the two are actually wired together.
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

from dynamic_venv_executor_chain import CreateVenvHandler, ExecuteCodeHandler
from secret_scrubber import MASK

SECRET_VALUE = "sk-live-must-not-touch-disk-7a21"
TEST_VENV_BASE_PATH = Path("/tmp/epicstaff-test-venvs")
# In the container these are installed into the venv; running the generated
# source directly here needs them on PYTHONPATH instead.
SHARED_PATH = Path(__file__).resolve().parents[3] / "shared"


def _context(**overrides):
    context = {
        "code": "def main(**kwargs):\n    return 1",
        "result_file_path": Path("/tmp/epicstaff-test/output.txt"),
        "entrypoint": "main",
        "func_kwargs": {},
        "global_kwargs": {},
        "execution_id": "exec-1",
        "storage_allowed_paths": None,
        "storage_org_prefix": None,
        "secrets": {},
    }
    context.update(overrides)
    return context


class TestBuildEnv:
    def test_returns_none_when_nothing_needs_configuring(self):
        # None means "inherit the parent environment", the pre-existing default.
        assert ExecuteCodeHandler().build_env(context=_context()) is None

    def test_secrets_are_json_encoded_under_one_variable(self):
        env = ExecuteCodeHandler().build_env(
            context=_context(secrets={"STRIPE KEY": SECRET_VALUE})
        )

        assert json.loads(env["EPICSTAFF_SECRETS"]) == {"STRIPE KEY": SECRET_VALUE}

    def test_a_single_variable_tolerates_names_that_are_not_identifiers(self):
        """Secret.name is a free-form CharField(max_length=128) and may contain
        spaces, so one variable per secret would require mangling names."""
        env = ExecuteCodeHandler().build_env(
            context=_context(secrets={"my key (prod)": SECRET_VALUE})
        )

        assert json.loads(env["EPICSTAFF_SECRETS"]) == {"my key (prod)": SECRET_VALUE}

    def test_empty_secrets_dict_sets_no_variable(self):
        env = ExecuteCodeHandler().build_env(
            context=_context(secrets={}, storage_org_prefix="org-1/")
        )

        assert "EPICSTAFF_SECRETS" not in env

    def test_storage_variables_are_unchanged(self):
        env = ExecuteCodeHandler().build_env(
            context=_context(
                storage_allowed_paths=["sessions/1/"], storage_org_prefix="org-1/"
            )
        )

        assert json.loads(env["STORAGE_ALLOWED_PATHS"]) == ["sessions/1/"]
        assert env["STORAGE_ORG_PREFIX"] == "org-1/"

    def test_storage_and_secrets_coexist(self):
        env = ExecuteCodeHandler().build_env(
            context=_context(storage_org_prefix="org-1/", secrets={"K": SECRET_VALUE})
        )

        assert env["STORAGE_ORG_PREFIX"] == "org-1/"
        assert json.loads(env["EPICSTAFF_SECRETS"]) == {"K": SECRET_VALUE}

    def test_inherits_the_parent_environment(self, monkeypatch):
        monkeypatch.setenv("SOME_INHERITED_VAR", "kept")

        env = ExecuteCodeHandler().build_env(
            context=_context(secrets={"K": SECRET_VALUE})
        )

        assert env["SOME_INHERITED_VAR"] == "kept"


class TestGeneratedSourceStaysClean:
    def test_wrap_code_output_contains_no_secret_value(self):
        """The disk-leak regression guard. wrap_code's return value is written
        to temp_code_path, so anything in it is written in cleartext to a file."""
        wrapped = ExecuteCodeHandler().wrap_code(
            code="def main(**kwargs):\n    return 1",
            result_file_path=Path("/tmp/epicstaff-test/output.txt"),
            entrypoint="main",
            func_kwargs={},
            global_kwargs={},
        )

        assert SECRET_VALUE not in wrapped
        assert "EPICSTAFF_SECRETS" not in wrapped

    def test_get_secret_is_in_scope_without_the_user_importing_it(self):
        """Node code calls get_secret("NAME") with no import line, the same way
        it already uses DotDict. Detection is unaffected either way --
        parse_secret_names matches the call, never an import -- so this is purely
        ergonomic, but it must actually be in scope or every node raises
        NameError at runtime."""
        wrapped = ExecuteCodeHandler().wrap_code(
            code='def main(**kwargs):\n    return get_secret("K")',
            result_file_path=Path("/tmp/epicstaff-test/output.txt"),
            entrypoint="main",
            func_kwargs={},
            global_kwargs={},
        )

        assert "from epicstaff_secrets import get_secret" in wrapped
        # Inside the try block, so a missing library reports through the same
        # stderr path as any other failure rather than killing the process
        # before the handler can report it.
        assert wrapped.index(
            "from epicstaff_secrets import get_secret"
        ) > wrapped.index("try:")

    def test_wrapped_code_runs_and_resolves_get_secret_from_the_environment(self):
        """End-to-end on the generated source: the preamble import plus
        EPICSTAFF_SECRETS in the environment must combine into a working
        get_secret call. Asserting on the string alone would not catch the
        library and the injected name drifting apart."""
        import json
        import os
        import subprocess
        import sys
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            result_path = Path(tmp) / "output.txt"
            wrapped = ExecuteCodeHandler().wrap_code(
                code='def main(**kwargs):\n    return get_secret("K")',
                result_file_path=result_path,
                entrypoint="main",
                func_kwargs={},
                global_kwargs={},
            )
            code_path = Path(tmp) / "code.py"
            code_path.write_text(wrapped)

            completed = subprocess.run(
                [sys.executable, str(code_path)],
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "EPICSTAFF_SECRETS": json.dumps({"K": SECRET_VALUE}),
                    "PYTHONPATH": str(SHARED_PATH),
                },
            )

            assert completed.returncode == 0, completed.stderr
            assert json.loads(result_path.read_text()) == SECRET_VALUE


def _execute(*, code: str, secrets: dict[str, str]):
    """Run `code` through the real ExecuteCodeHandler and return its CodeResultData.

    A real subprocess rather than a stub: the point of these tests is that the
    scrubber sits between the child's pipes and everything downstream, and only an
    actual execution exercises that seam.
    """
    with tempfile.TemporaryDirectory() as tmp:
        context = {
            "python_executable": sys.executable,
            "temp_code_path": str(Path(tmp) / "code.py"),
            "result_file_path": Path(tmp) / "output.txt",
            "code": code,
            "entrypoint": "main",
            "func_kwargs": {},
            "global_kwargs": {},
            "execution_id": "exec-1",
            "storage_allowed_paths": None,
            "storage_org_prefix": None,
            "secrets": secrets,
        }
        return asyncio.run(ExecuteCodeHandler().handle(context))


class TestOutputStaysClean:
    @pytest.fixture(autouse=True)
    def shared_libs_on_path(self, monkeypatch):
        """epicstaff_secrets reaches the child through PYTHONPATH here; the
        container installs it into the venv instead. build_env copies os.environ
        (and returns None to inherit it when there are no secrets), so either way
        this is what puts the library in the child's import path."""
        monkeypatch.setenv("PYTHONPATH", str(SHARED_PATH))

    def test_a_printed_secret_is_masked_in_stdout(self):
        result = _execute(
            code='def main(**kwargs):\n    print(get_secret("K"))\n    return 1',
            secrets={"K": SECRET_VALUE},
        )

        assert SECRET_VALUE not in result.stdout
        assert MASK in result.stdout

    def test_a_secret_in_an_exception_message_is_masked_in_stderr(self):
        """The likeliest accidental leak. wrap_code's except block prints str(e) to
        stderr verbatim, so any library error echoing an auth header lands here
        without the author writing a single print."""
        result = _execute(
            code='def main(**kwargs):\n    raise ValueError(get_secret("K"))',
            secrets={"K": SECRET_VALUE},
        )

        assert SECRET_VALUE not in result.stderr
        assert MASK in result.stderr

    def test_a_returned_secret_is_masked_in_result_data(self):
        """result_data is json.dumps of the return value, and it reaches the SSE
        stream and the REST endpoint, so it needs the same treatment as the pipes."""
        result = _execute(
            code='def main(**kwargs):\n    return {"token": get_secret("K")}',
            secrets={"K": SECRET_VALUE},
        )

        assert result.returncode == 0
        assert SECRET_VALUE not in result.result_data
        assert MASK in result.result_data

    def test_masking_does_not_change_the_return_code(self):
        """Masking is silent by design: a flow that logs a secret today keeps
        working, it just stops publishing the value."""
        result = _execute(
            code='def main(**kwargs):\n    print(get_secret("K"))\n    return 1',
            secrets={"K": SECRET_VALUE},
        )

        assert result.returncode == 0

    def test_output_is_untouched_when_the_node_declares_no_secrets(self):
        """The no-regression case: with nothing to scrub, every stream is
        byte-identical to what the child wrote."""
        result = _execute(
            code='def main(**kwargs):\n    print("plain output")\n    return {"a": 1}',
            secrets={},
        )

        assert result.stdout == "plain output\n"
        assert result.result_data == '{"a": 1}'
        assert result.returncode == 0


class TestLibraryRegistration:
    @pytest.fixture
    def clear_test_venvs(self):
        """Mirrors clear_venvs_and_executions in fixtures.py: the hash-keyed
        venv directory this test creates must not survive the test, or the
        `if not venv_path.exists(): ...` branch in handle() short-circuits on
        every later run and the test stops exercising real venv creation."""
        yield
        shutil.rmtree(TEST_VENV_BASE_PATH)

    def test_epicstaff_secrets_is_always_in_the_venv(self, clear_test_venvs):
        """Unconditional, unlike epicstaff_storage's use_storage gate: if the
        library were conditional, forgetting to declare a secret would surface
        as ImportError, which points at the wrong problem."""
        import asyncio

        context = {
            "libraries": ["requests"],
            "base_venv_path": str(TEST_VENV_BASE_PATH),
            "execution_id": "exec-1",
        }
        handler = CreateVenvHandler()
        # No next handler and an existing-or-created venv path: handle() returns
        # after computing the library set, which is all this asserts.
        asyncio.run(handler.handle(context))

        assert "/app/src/shared/epicstaff_secrets" in context["libraries"]
