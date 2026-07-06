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


class TestShellJobResultTool:
    def test_unknown_job_id_returns_error(self, sandbox_dir):
        job_result_main = load_tool_main("shell_job_result_tool").main

        # Well-formed (32 lowercase hex chars, matching uuid4().hex) but no
        # such job directory exists.
        result = job_result_main(job_id="0" * 32)

        assert result.startswith("Error:")
        assert "no job found" in result

    def test_missing_job_id_returns_error(self, sandbox_dir):
        job_result_main = load_tool_main("shell_job_result_tool").main

        result = job_result_main(job_id="")

        assert result.startswith("Error:")
        assert "job_id" in result

    def test_invalid_job_id_characters_rejected(self, sandbox_dir):
        job_result_main = load_tool_main("shell_job_result_tool").main

        result = job_result_main(job_id="../../etc/passwd")

        assert result.startswith("Error:")
        assert "invalid job_id" in result

    def test_job_id_wrong_length_rejected(self, sandbox_dir):
        job_result_main = load_tool_main("shell_job_result_tool").main

        result = job_result_main(job_id="abc123")

        assert result.startswith("Error:")
        assert "invalid job_id" in result

    def test_job_id_uppercase_hex_rejected(self, sandbox_dir):
        job_result_main = load_tool_main("shell_job_result_tool").main

        # uuid4().hex is always lowercase — uppercase hex must not be accepted.
        result = job_result_main(job_id="A" * 32)

        assert result.startswith("Error:")
        assert "invalid job_id" in result

    def test_job_id_alphanumeric_but_non_hex_rejected(self, sandbox_dir):
        job_result_main = load_tool_main("shell_job_result_tool").main

        # 32 alphanumeric chars that are not valid hex (contains 'g', 'z')
        # must be rejected now that validation is hex-specific, not just
        # alnum.
        result = job_result_main(job_id="g" * 16 + "z" * 16)

        assert result.startswith("Error:")
        assert "invalid job_id" in result
