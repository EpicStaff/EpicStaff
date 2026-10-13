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
import sys
from pathlib import Path

import pytest

pytest.importorskip(
    "pwd",
    reason="POSIX-only: sandbox isolation requires pwd/landlock; runs in the Linux image",
)

import settings
import dynamic_venv_executor_chain as chain_mod
from dynamic_venv_executor_chain import ExecuteCodeHandler
from secret_scrubber import MASK

from conftest import copy_shared_libs_into_jail, make_execute_context

SECRET_VALUE = "sk-live-must-not-touch-disk-7a21"
# In the container these are installed into the venv; running the generated
# source directly here needs them on PYTHONPATH instead.
SHARED_PATH = Path(__file__).resolve().parents[3] / "shared"


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


def _execute(*, base_dir: Path, code: str, secrets: dict[str, str]):
    """Run `code` through the real ExecuteCodeHandler and return its CodeResultData.

    A real subprocess rather than a stub: the point of these tests is that the
    scrubber sits between the child's pipes and everything downstream, and only an
    actual execution exercises that seam.
    """
    context = make_execute_context(
        base_dir,
        python_executable=sys.executable,
        code=code,
        execution_id="exec-1",
        secrets=secrets,
    )
    return asyncio.run(ExecuteCodeHandler().handle(context))


@pytest.fixture
def shared_libs_on_path(tmp_path, monkeypatch):
    """wrap_code's preamble imports epicstaff_secrets. Production installs it into the
    venv, which the jail allows; these tests run without a venv, and src/shared is
    outside every allowlist entry, so the library is copied into exec_dir instead.
    See copy_shared_libs_into_jail."""
    shared_libs_path = copy_shared_libs_into_jail(tmp_path)
    real_build_base_env = chain_mod.build_base_env
    monkeypatch.setattr(
        chain_mod,
        "build_base_env",
        lambda pe: {**real_build_base_env(pe), "PYTHONPATH": str(shared_libs_path)},
    )


# Where a secret can leave the child: printed, in an exception message (wrap_code
# prints str(e) to stderr - the likeliest accidental leak), or returned (result_data
# reaches the SSE stream and the REST endpoint).
LEAKS = {
    "stdout": ('def main(**kwargs):\n    print(get_secret("K"))\n    return 1', 0),
    "stderr": ('def main(**kwargs):\n    raise ValueError(get_secret("K"))', None),
    "result_data": ('def main(**kwargs):\n    return {"token": get_secret("K")}', 0),
}


def _stream(result, name: str) -> str:
    return getattr(result, name) or ""


@pytest.mark.usefixtures("shared_libs_on_path")
@pytest.mark.parametrize("stream", LEAKS)
def test_a_secret_is_masked_in_every_stream_without_changing_the_outcome(
    tmp_path, monkeypatch, stream
):
    monkeypatch.setattr(settings, "MASK_SECRET", True)
    code, expected_returncode = LEAKS[stream]

    result = _execute(base_dir=tmp_path, code=code, secrets={"K": SECRET_VALUE})

    assert SECRET_VALUE not in _stream(result, stream)
    assert MASK in _stream(result, stream)
    # Masking is silent: a flow that logs a secret keeps working, it just stops publishing it.
    if expected_returncode is None:
        assert result.returncode != 0
    else:
        assert result.returncode == expected_returncode


@pytest.mark.usefixtures("shared_libs_on_path")
@pytest.mark.parametrize("stream", LEAKS)
def test_masking_off_lets_the_developers_own_secret_through(tmp_path, monkeypatch, stream):
    """The documented debugging mode."""
    monkeypatch.setattr(settings, "MASK_SECRET", False)
    code, _ = LEAKS[stream]

    result = _execute(base_dir=tmp_path, code=code, secrets={"K": SECRET_VALUE})

    assert SECRET_VALUE in _stream(result, stream)
    assert MASK not in _stream(result, stream)


@pytest.mark.usefixtures("shared_libs_on_path")
def test_output_is_untouched_when_the_node_declares_no_secrets(tmp_path):
    result = _execute(
        base_dir=tmp_path,
        code='def main(**kwargs):\n    print("plain output")\n    return {"a": 1}',
        secrets={},
    )

    assert result.stdout == "plain output\n"
    assert result.result_data == '{"a": 1}'
    assert result.returncode == 0


TEMP_ACCESS_KEY = "temp-ak-must-not-leak"
TEMP_SECRET_KEY = "temp-sk-must-not-leak"


@pytest.mark.usefixtures("shared_libs_on_path")
@pytest.mark.parametrize("mask_secret", [True, False])
def test_temporary_storage_credentials_are_masked_whatever_mask_secret_says(
    tmp_path, monkeypatch, mask_secret
):
    """MASK_SECRET=false is an opt-out for the developer's own secrets, never for the
    per-execution storage credentials - including when no user secret is declared."""
    monkeypatch.setattr(settings, "MASK_SECRET", mask_secret)
    context = make_execute_context(
        tmp_path,
        python_executable=sys.executable,
        code=(
            "def main(**kwargs):\n"
            "    import os\n"
            "    print(os.environ['STORAGE_ACCESS_KEY'], os.environ['STORAGE_SECRET_KEY'])\n"
            "    return os.environ['STORAGE_SECRET_KEY']\n"
        ),
        use_storage=True,
        temp_storage_access_key=TEMP_ACCESS_KEY,
        temp_storage_secret_key=TEMP_SECRET_KEY,
        secrets={},
    )

    result = asyncio.run(ExecuteCodeHandler().handle(context))

    assert result.returncode == 0, result.stderr
    for leaked in (result.stdout, result.result_data):
        assert TEMP_ACCESS_KEY not in leaked
        assert TEMP_SECRET_KEY not in leaked
    assert result.stdout.count(MASK) == 2
