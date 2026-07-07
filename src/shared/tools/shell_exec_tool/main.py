# Shell Exec Tool
#
# Hardened variant of the existing CLI Executor Tool (cli_tool/) — this tool
# is intentionally a separate, duplicate implementation (see EST-3285 spec:
# "duplication acceptable"), never modify cli_tool/ to add these behaviors.
#
# Adds: merged stdout/stderr capped at OUTPUT_CAP_CHARS with an explicit
# truncation marker, timeout-based process-tree kill with partial output,
# and a background mode that detaches the process and writes its output/exit
# code continuously to a job directory under
# `.jobs/<session_id>/<job_id>/` on the sandbox working root, namespaced by
# the caller's session id so one session can't read another session's job
# (see _session_namespace()) — each sandbox execution is a fresh process, so
# results are retrieved later via the separate Shell Job Result Tool
# (shell_job_result_tool/).

import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

OUTPUT_CAP_CHARS = 30000
DEFAULT_TIMEOUT_MS = 120000
MAX_TIMEOUT_MS = 600000
JOBS_DIR_NAME = ".jobs"
NO_SESSION_NAMESPACE = "_nosession"

# Headroom over the character cap for worst-case UTF-8 (up to 4 bytes/char),
# used to bound in-memory/on-disk buffering *before* the char-level
# _truncate() below is applied -- the goal here is capping memory/disk use
# while a command is still running, not the final displayed length.
#
# NOTE: this is also the exact byte count `head -c` truncates a background
# job's output.log to (see _spawn_background below). shell_job_result_tool's
# own OUTPUT_READ_CAP_BYTES constant must stay equal to this value -- that's
# what lets it detect "this background job's output was cut off at the cap"
# by comparing the file's on-disk size to its own copy of the same number.
# There's no shared module between tool dirs (self-contained by convention),
# so keep both literals (30000 * 4) in sync by hand if OUTPUT_CAP_CHARS ever
# changes in either file.
OUTPUT_CAP_BYTES = OUTPUT_CAP_CHARS * 4
READ_CHUNK_BYTES = 65536


def _working_root() -> Path:
    return Path(os.getenv("CONTAINER_SAVEFILES_PATH", "."))


def _session_namespace() -> str:
    """Resolve the caller's sandbox session id into a single, safe path
    component used to namespace background job directories under `.jobs/`.

    `session_id` is not a function argument -- it's injected by the crew
    engine as a bare module global for every built-in python-code tool call
    (see `global_kwargs["session_id"]` in crew_node.py and the identical
    `globals().get("session_id")` pattern in subflow_tool/main.py). Without
    this namespace, `.jobs/<job_id>` on the shared savefiles volume lets any
    session read/guess another session's job output.

    Falls back to a shared `_nosession` namespace -- consistent with
    shell_job_result_tool -- when no session_id is injected (e.g. ad-hoc /
    manual invocation outside a crew-engine session), and fails closed to
    that same namespace for anything that isn't a plain numeric id (rejects
    path separators, `..`, empty strings, etc. as unsafe path components).
    """
    session_id = globals().get("session_id")
    if session_id is None:
        return NO_SESSION_NAMESPACE

    text = str(session_id).strip()
    # `str.isascii()` is required in addition to `str.isdigit()`: the latter
    # also accepts non-ASCII "digit" characters (e.g. superscripts, fullwidth
    # digits), which would otherwise slip through as a "plain numeric id".
    if not text.isascii() or not text.isdigit():
        return NO_SESSION_NAMESPACE

    return text


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


def _start_capped_reader(process: subprocess.Popen):
    """Start a daemon thread that reads `process.stdout` incrementally,
    stopping once OUTPUT_CAP_BYTES total bytes have been buffered -- a
    runaway command never gets to buffer more than that, unlike
    `process.communicate()`. Returns (reader_thread, get_output), where
    get_output() -> (bytes_so_far, cap_hit)."""
    chunks: list[bytes] = []
    state = {"total_bytes": 0, "cap_hit": False}
    lock = threading.Lock()

    def _reader() -> None:
        try:
            while True:
                chunk = process.stdout.read(READ_CHUNK_BYTES)
                if not chunk:
                    return
                with lock:
                    chunks.append(chunk)
                    state["total_bytes"] += len(chunk)
                    if state["total_bytes"] >= OUTPUT_CAP_BYTES:
                        state["cap_hit"] = True
                        return
        except (ValueError, OSError):
            # stdout pipe closed out from under us (e.g. right after a kill)
            # -- nothing more to read.
            return

    reader_thread = threading.Thread(target=_reader, daemon=True)
    reader_thread.start()

    def get_output():
        with lock:
            return b"".join(chunks), state["cap_hit"]

    return reader_thread, get_output


def _finish_process(
    process: subprocess.Popen, reader_thread: threading.Thread, should_kill: bool
) -> None:
    """Kill the process tree if it timed out or hit the output cap, then wait
    for its exit code (with a defensive fallback kill if wait itself hangs)."""
    if should_kill:
        # Kill first: this closes the pipe's write end, which unblocks the
        # reader thread's in-flight read() call with EOF.
        _kill_process_tree(process.pid)
        reader_thread.join(timeout=5)

    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process.pid)
        try:
            process.wait(timeout=5)
        except Exception:
            pass


def _run_foreground(command: str, timeout_seconds: float):
    """Run `command` and return (output, exit_code, timed_out, cap_hit).

    Unlike `process.communicate()`, output is read incrementally and capped
    at OUTPUT_CAP_BYTES (see `_start_capped_reader`) -- a runaway command
    (e.g. a print loop) is killed as soon as the cap is hit instead of
    buffering unbounded output in memory first.
    """
    popen_kwargs = dict(
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(_working_root()),
    )
    if hasattr(os, "setsid"):
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(command, **popen_kwargs)

    reader_thread, get_output = _start_capped_reader(process)
    reader_thread.join(timeout=timeout_seconds)

    timed_out = reader_thread.is_alive()
    _, cap_hit = get_output()

    _finish_process(process, reader_thread, should_kill=timed_out or cap_hit)

    output_bytes, cap_hit = get_output()

    # Manual universal-newline translation: the previous text=True +
    # communicate() implementation normalized "\r\n"/"\r" to "\n" for us;
    # reading raw bytes here (required for an exact byte cap) bypasses that,
    # so replicate it explicitly to keep output/char-count behavior
    # unchanged (notably on Windows).
    output = output_bytes.decode("utf-8", errors="replace")
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    return output, process.returncode, timed_out, cap_hit


def _format_foreground_result(
    output: str,
    exit_code,
    timed_out: bool,
    timeout_ms: int,
    timeout_clamped: bool,
    cap_hit: bool = False,
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
    elif cap_hit:
        parts.append(
            "\n(command was killed after exceeding the in-memory output cap "
            "while running — showing partial output)"
        )
    elif exit_code is None:
        # Only reachable if the process survived being killed twice across
        # two 5s waits in _finish_process -- returncode was never set.
        parts.append("\n(exit code: unknown — process could not be confirmed dead)")
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
    `cmd.exe` (local/dev).

    Job directories are namespaced by the caller's sandbox session id (see
    `_session_namespace()`) so one session can never write into -- or, via
    shell_job_result_tool, read -- another session's job output.
    """
    working_root = _working_root()
    jobs_dir = working_root / JOBS_DIR_NAME / _session_namespace()
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
                f'echo %errorlevel% > "{exit_code_file}"\r\n'
                # No exact `head -c` equivalent on Windows. This truncates the
                # output file *after* the command has already finished, so it
                # does NOT bound disk usage while the command is running --
                # accepted limitation; this branch is local/dev only, the
                # production sandbox is POSIX (see below). `fsutil seteof`
                # truncates in place without reading the file into memory.
                f'for %%A in ("{output_file}") do if %%~zA GTR {OUTPUT_CAP_BYTES} '
                f'(fsutil file seteof "{output_file}" {OUTPUT_CAP_BYTES} >nul 2>&1)\r\n',
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
                "#!/bin/bash\n"
                # `head -c` bounds the output file *while the command is
                # still running* -- this is what actually protects the
                # shared savefiles volume from an unbounded background job.
                # `command` runs inside a subshell piped through head, so
                # `${PIPESTATUS[0]}` is the subshell's exit code -- which
                # equals the command's own exit code ONLY while its output
                # stays under the cap. Once `head` has read its N bytes it
                # exits, closing the pipe; if the command keeps writing past
                # that point it gets SIGPIPE/EPIPE, and PIPESTATUS[0] then
                # reflects *that* (typically 141), not the command's own
                # final exit status. This is an accepted, documented
                # limitation of bounding a live stream this way -- see
                # shell_job_result_tool.main(), which detects an output.log
                # at (or past) the cap and surfaces this caveat explicitly
                # instead of reporting a bare, possibly-misleading exit code.
                f'({command}) 2>&1 | head -c {OUTPUT_CAP_BYTES} > "{output_file}"\n'
                f'echo ${{PIPESTATUS[0]}} > "{exit_code_file}"\n',
                encoding="utf-8",
            )
            script_path.chmod(0o755)
            popen_args = ["/bin/bash", str(script_path)]
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
            output, exit_code, timed_out, cap_hit = _run_foreground(
                command, timeout_seconds
            )
        except Exception as e:
            return f"Error: failed to execute command: {e}"

        return _format_foreground_result(
            output, exit_code, timed_out, timeout_ms, timeout_clamped, cap_hit
        )
    except Exception as e:
        return f"Error: shell execution failed. Unexpected exception: {e}"
