# Shell Exec Tool
#
# Hardened variant of the existing CLI Executor Tool (cli_tool/) — this tool
# is intentionally a separate, duplicate implementation (see EST-3285 spec:
# "duplication acceptable"), never modify cli_tool/ to add these behaviors.
#
# Adds: merged stdout/stderr capped at OUTPUT_CAP_CHARS with an explicit
# truncation marker, timeout-based process-tree kill with partial output,
# and a background mode that detaches the process and writes its output/exit
# code continuously to a job directory under the sandbox working root — each
# sandbox execution is a fresh process, so results are retrieved later via
# the separate Shell Job Result Tool (shell_job_result_tool/).

import json
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path

OUTPUT_CAP_CHARS = 30000
DEFAULT_TIMEOUT_MS = 120000
MAX_TIMEOUT_MS = 600000
JOBS_DIR_NAME = ".jobs"


def _working_root() -> Path:
    return Path(os.getenv("CONTAINER_SAVEFILES_PATH", "."))


def _truncate(text: str, cap: int = OUTPUT_CAP_CHARS):
    if len(text) <= cap:
        return text, False
    return text[:cap], True


def _kill_process_tree(pid: int) -> None:
    """Best-effort kill of a process and all its descendants. Uses psutil for
    cross-platform coverage (shell=True spawns a shell that spawns the real
    command, so killing just the Popen pid is not enough)."""
    try:
        import psutil

        try:
            parent = psutil.Process(pid)
        except psutil.NoSuchProcess:
            return

        children = []
        try:
            children = parent.children(recursive=True)
        except psutil.NoSuchProcess:
            pass

        for child in children:
            try:
                child.kill()
            except psutil.NoSuchProcess:
                pass

        try:
            parent.kill()
        except psutil.NoSuchProcess:
            pass

        psutil.wait_procs([parent, *children], timeout=5)
    except ImportError:
        import signal

        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass


def _run_foreground(command: str, timeout_seconds: float):
    popen_kwargs = dict(
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        cwd=str(_working_root()),
    )
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)

    try:
        output, _ = process.communicate(timeout=timeout_seconds)
        return output or "", process.returncode, False
    except subprocess.TimeoutExpired:
        _kill_process_tree(process.pid)
        try:
            output, _ = process.communicate(timeout=5)
        except Exception:
            output = ""
        return output or "", process.returncode, True


def _format_foreground_result(
    output: str,
    exit_code,
    timed_out: bool,
    timeout_ms: int,
    timeout_clamped: bool,
) -> str:
    text, truncated = _truncate(output)
    parts = [text]

    if truncated:
        parts.append(
            f"\n(output truncated at {OUTPUT_CAP_CHARS} characters; "
            f"{len(output)} total characters produced)"
        )

    if timeout_clamped:
        parts.append(f"\n(timeout_ms capped at {MAX_TIMEOUT_MS})")

    if timed_out:
        parts.append(
            f"\n(command timed out after {timeout_ms} ms and was killed — showing "
            "partial output)"
        )
    elif exit_code != 0:
        parts.append(f"\n(exit code: {exit_code})")

    return "".join(parts)


def _spawn_background(command: str):
    """Detach `command` into its own process, writing output continuously and
    the exit code only once finished — via a tiny generated script file, so
    it survives independently of this tool's own (short-lived) process. A
    script file is used instead of a single Popen(shell=True, ...) string
    because the redirect-then-record-exit-code sequence needs native shell
    syntax that differs between POSIX `sh` (production sandbox) and Windows
    `cmd.exe` (local/dev)."""
    working_root = _working_root()
    jobs_dir = working_root / JOBS_DIR_NAME
    jobs_dir.mkdir(parents=True, exist_ok=True)

    job_id = uuid.uuid4().hex
    job_dir = jobs_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    output_file = job_dir / "output.log"
    exit_code_file = job_dir / "exit_code"
    status_file = job_dir / "status.json"

    output_file.touch()

    try:
        if os.name == "nt":
            script_path = job_dir / "run.bat"
            script_path.write_text(
                "@echo off\r\n"
                f'call {command} > "{output_file}" 2>&1\r\n'
                f'echo %errorlevel% > "{exit_code_file}"\r\n',
                encoding="utf-8",
            )
            popen_args = ["cmd", "/c", str(script_path)]
            popen_kwargs = dict(
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
        else:
            script_path = job_dir / "run.sh"
            script_path.write_text(
                "#!/bin/sh\n"
                f'({command}) > "{output_file}" 2>&1\n'
                f'echo $? > "{exit_code_file}"\n',
                encoding="utf-8",
            )
            script_path.chmod(0o755)
            popen_args = ["/bin/sh", str(script_path)]
            popen_kwargs = dict(
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        subprocess.Popen(popen_args, cwd=str(working_root), **popen_kwargs)
    except Exception as e:
        return None, f"Error: failed to start background job: {e}"

    status_file.write_text(
        json.dumps({"command": command, "started_at": time.time()}), encoding="utf-8"
    )

    return job_id, None


def main(
    command: str,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    run_in_background: bool = False,
) -> str:
    """
    Execute a shell command inside the sandbox. Merges stdout/stderr, caps
    output at 30000 characters (announcing truncation), and on timeout kills
    the whole process tree and returns partial output. Non-zero exit codes
    are reported in the output text, never raised. When run_in_background is
    true, the command is detached and a job id is returned immediately;
    retrieve its output/status later with the Shell Job Result Tool. Never
    raises: all failures are returned as readable error strings.
    """
    try:
        if not command or not command.strip():
            return "Error: command argument is mandatory and was not given to the tool."

        timeout_ms = timeout_ms or DEFAULT_TIMEOUT_MS
        if timeout_ms <= 0:
            return "Error: timeout_ms must be a positive integer."

        timeout_clamped = timeout_ms > MAX_TIMEOUT_MS
        if timeout_clamped:
            timeout_ms = MAX_TIMEOUT_MS

        run_in_background = bool(run_in_background)

        if run_in_background:
            job_id, error = _spawn_background(command)
            if error:
                return error
            return (
                f"Started background job {job_id}. Use the Shell Job Result Tool "
                f"with job_id='{job_id}' to retrieve its output and status."
            )

        timeout_seconds = timeout_ms / 1000.0

        try:
            output, exit_code, timed_out = _run_foreground(command, timeout_seconds)
        except Exception as e:
            return f"Error: failed to execute command: {e}"

        return _format_foreground_result(
            output, exit_code, timed_out, timeout_ms, timeout_clamped
        )
    except Exception as e:
        return f"Error: shell execution failed. Unexpected exception: {e}"
