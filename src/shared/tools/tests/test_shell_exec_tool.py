import sys

import pytest

from conftest import load_tool_main

shell_exec_main = load_tool_main("shell_exec_tool").main

IS_WINDOWS = sys.platform.startswith("win")


def _echo_command(text: str) -> str:
    if IS_WINDOWS:
        return f"echo {text}"
    return f"echo {text}"


class TestShellExecToolForeground:
    def test_happy_path_returns_merged_output(self, sandbox_dir):
        result = shell_exec_main(command=_echo_command("hello"))

        assert "hello" in result

    def test_non_zero_exit_reported_never_raised(self, sandbox_dir):
        if IS_WINDOWS:
            command = "exit 3"
        else:
            command = "exit 3"

        result = shell_exec_main(command=command)

        assert "exit code: 3" in result

    def test_missing_command_returns_error(self, sandbox_dir):
        result = shell_exec_main(command="")

        assert result.startswith("Error:")
        assert "command" in result

    def test_output_truncation_is_announced(self, sandbox_dir):
        python_exe = sys.executable

        command = f'{python_exe} -c "print(\'x\' * 40000)"'

        result = shell_exec_main(command=command)

        assert "truncated at 30000 characters" in result
        assert "40001 total characters produced" in result

    def test_timeout_kills_process_and_returns_partial_output(self, sandbox_dir):
        tool_module = load_tool_main("shell_exec_tool")

        if IS_WINDOWS:
            command = 'python -c "import sys,time; print(\'partial\'); sys.stdout.flush(); time.sleep(30)"'
        else:
            command = "python3 -c \"import sys,time; print('partial'); sys.stdout.flush(); time.sleep(30)\""

        result = tool_module.main(command=command, timeout_ms=500)

        assert "partial" in result
        assert "timed out after 500 ms" in result

    def test_timeout_ms_capped_and_announced(self, sandbox_dir):
        result = shell_exec_main(
            command=_echo_command("hi"), timeout_ms=10_000_000
        )

        assert "timeout_ms capped at 600000" in result

    def test_output_exceeding_cap_kills_process_without_buffering_it_all(
        self, sandbox_dir
    ):
        import time

        python_exe = sys.executable
        # Emits far more than the 120000-byte in-memory cap (30000 chars * 4)
        # in ~64KB chunks. If the cap weren't enforced while reading, the
        # tool would have to buffer the *entire* ~12.5MB of output before
        # even reaching the existing char-level truncation step.
        command = (
            f"{python_exe} -c "
            '"import sys; [sys.stdout.write(\'x\' * 65536) for _ in range(200)]"'
        )

        started = time.monotonic()
        result = shell_exec_main(command=command, timeout_ms=20000)
        elapsed = time.monotonic() - started

        assert "exceeding the in-memory output cap" in result
        assert "truncated at 30000 characters" in result
        # The cap must be hit and the process killed well before either the
        # full ~12.5MB of output is produced or the 20s timeout elapses.
        assert elapsed < 10

    def test_format_result_handles_unknown_exit_code_gracefully(self, sandbox_dir):
        # Only reachable in practice if a process survives being killed
        # twice across two 5s waits in _finish_process, leaving
        # process.returncode as None -- exercised directly here since that
        # path can't be reliably reproduced with a real subprocess.
        tool_module = load_tool_main("shell_exec_tool")

        result = tool_module._format_foreground_result(
            output="partial output",
            exit_code=None,
            timed_out=False,
            timeout_ms=5000,
            timeout_clamped=False,
            cap_hit=False,
        )

        assert "partial output" in result
        assert "exit code: unknown" in result
        assert "exit code: None" not in result


class TestShellExecToolBackground:
    def test_background_returns_job_id_immediately(self, sandbox_dir):
        result = shell_exec_main(
            command=_echo_command("bg-hello"), run_in_background=True
        )

        assert result.startswith("Started background job ")

    def test_background_job_output_and_result_retrieval(self, sandbox_dir):
        import time

        job_result_main = load_tool_main("shell_job_result_tool").main

        result = shell_exec_main(
            command=_echo_command("bg-world"), run_in_background=True
        )
        job_id = result.split("job ")[1].split(".")[0]

        deadline = time.time() + 10
        job_result = ""
        while time.time() < deadline:
            job_result = job_result_main(job_id=job_id)
            if "finished" in job_result:
                break
            time.sleep(0.2)

        assert "bg-world" in job_result
        assert "finished" in job_result
        assert "exit code: 0" in job_result

    def test_job_result_running_status_before_completion(self, sandbox_dir):
        tool_module = load_tool_main("shell_exec_tool")
        job_result_main = load_tool_main("shell_job_result_tool").main

        if IS_WINDOWS:
            command = 'python -c "import time; time.sleep(3)"'
        else:
            command = "python3 -c \"import time; time.sleep(3)\""

        result = tool_module.main(command=command, run_in_background=True)
        job_id = result.split("job ")[1].split(".")[0]

        job_result = job_result_main(job_id=job_id)

        assert "status: running" in job_result

    def test_background_job_writes_under_caller_session_namespace(
        self, sandbox_dir
    ):
        tool_module = load_tool_main("shell_exec_tool")
        tool_module.session_id = 4242

        result = tool_module.main(
            command=_echo_command("scoped-job"), run_in_background=True
        )
        job_id = result.split("job ")[1].split(".")[0]

        assert (sandbox_dir / ".jobs" / "4242" / job_id).is_dir()
        assert not (sandbox_dir / ".jobs" / job_id).exists()

    def test_background_job_falls_back_to_nosession_namespace(self, sandbox_dir):
        tool_module = load_tool_main("shell_exec_tool")
        # No session_id global injected at all.

        result = tool_module.main(
            command=_echo_command("no-session-job"), run_in_background=True
        )
        job_id = result.split("job ")[1].split(".")[0]

        assert (sandbox_dir / ".jobs" / "_nosession" / job_id).is_dir()
