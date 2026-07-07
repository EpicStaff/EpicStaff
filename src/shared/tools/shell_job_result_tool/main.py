# Shell Job Result Tool
#
# Companion to shell_exec_tool/: retrieves output and status for a job
# started with run_in_background=true. See shell_exec_tool/main.py for how
# the job directory (.jobs/<session_id>/<job_id>/) is populated.

import os
from pathlib import Path

OUTPUT_CAP_CHARS = 30000
JOBS_DIR_NAME = ".jobs"
NO_SESSION_NAMESPACE = "_nosession"

# Headroom over the character cap for worst-case UTF-8 (up to 4 bytes/char) --
# bounds how much of a (potentially still-growing, unbounded) job output file
# is read into memory before the char-level _truncate() below is applied.
#
# NOTE: this must stay equal to shell_exec_tool's own OUTPUT_CAP_BYTES
# (same formula: 30000 * 4) -- that's the exact byte count `head -c` bounds a
# background job's output.log to, and this constant is what main() compares
# the file's on-disk size against to detect "this job's output was cut off
# at the cap" (see `background_output_capped` below). No shared module
# between tool dirs (self-contained by convention), so keep both literals in
# sync by hand if OUTPUT_CAP_CHARS ever changes in either file.
OUTPUT_READ_CAP_BYTES = OUTPUT_CAP_CHARS * 4


def _working_root() -> Path:
    return Path(os.getenv("CONTAINER_SAVEFILES_PATH", "."))


def _session_namespace() -> str:
    """Resolve the caller's sandbox session id into a single, safe path
    component used to resolve a job directory under `.jobs/`.

    `session_id` is not a function argument -- it's injected by the crew
    engine as a bare module global for every built-in python-code tool call
    (see `global_kwargs["session_id"]` in crew_node.py and the identical
    `globals().get("session_id")` pattern in subflow_tool/main.py).
    Resolving job_id only within the caller's own session namespace is what
    makes cross-session job reads impossible by construction -- job ids from
    another session simply won't exist under this namespace.

    Falls back to a shared `_nosession` namespace -- consistent with
    shell_exec_tool, which writes background jobs to that same namespace
    when it has no session_id either -- when no session_id is injected (e.g.
    ad-hoc / manual invocation outside a crew-engine session), and fails
    closed to that same namespace for anything that isn't a plain numeric id
    (rejects path separators, `..`, empty strings, etc. as unsafe path
    components).
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


def _read_capped(path: Path, cap_bytes: int) -> tuple[str, bool, int]:
    """Read at most `cap_bytes` of a (potentially unbounded / still-growing)
    output file instead of loading it whole via read_text(). Returns
    (text, file_was_larger_than_cap, total_size_on_disk_bytes)."""
    try:
        total_size = path.stat().st_size
    except FileNotFoundError:
        return "", False, 0

    try:
        with open(path, "rb") as f:
            raw = f.read(cap_bytes)
    except FileNotFoundError:
        return "", False, 0

    text = raw.decode("utf-8", errors="replace")
    return text, total_size > len(raw), total_size


# Known ambiguous/failure-mode states this tool cannot fully distinguish
# (documented here for future readers, not handled specially -- each is a
# rare edge case of the underlying job-directory protocol written by
# shell_exec_tool._spawn_background, not a bug in this file):
#
#   (a) The background script's `echo ... > exit_code` write can itself fail
#       (disk full, permission error on the shared savefiles volume, etc.).
#       If it does, `exit_code_file.exists()` never becomes true even though
#       the command has long since finished -- this tool has no way to tell
#       "still running" apart from "finished, but exit-code write failed",
#       and will report "status: running" forever for that job.
#   (b) If the bash output redirect itself fails to open (e.g. the job
#       directory or output.log became inaccessible after the job started),
#       the command can still finish and successfully record a real exit
#       code, while output.log is left zero-byte or missing -- this shows up
#       here as a normal "status: finished (exit code: ...)" with empty
#       output, indistinguishable from a command that legitimately produced
#       no output.
#   (c) On Windows, `_spawn_background`'s post-hoc `fsutil file seteof`
#       truncation runs with its own stderr suppressed (`>nul 2>&1`) -- if
#       `fsutil` itself fails (e.g. not available, or the file is locked),
#       that failure is silent and output.log is simply left over the cap
#       uncapped. This tool then reads and reports whatever size the file
#       actually is; it does not verify the Windows-side cap was applied.
#       Accepted: Windows background jobs are a local/dev-only path, the
#       production sandbox is POSIX (where head -c enforces the cap at
#       write time, not post-hoc).
def main(job_id: str) -> str:
    """
    Read the current output and running/finished status of a background job
    started by the Shell Exec Tool. Only resolves jobs started by the
    caller's own sandbox session — job ids from other sessions never
    resolve. Never raises: all failures are returned as readable error
    strings.
    """
    try:
        if not job_id or not job_id.strip():
            return "Error: job_id argument is mandatory and was not given to the tool."

        # job_id is generated by uuid.uuid4().hex (shell_exec_tool) — always
        # exactly 32 lowercase hex characters. Reject anything else outright
        # rather than trusting it as a path component.
        if len(job_id) != 32 or not all(c in "0123456789abcdef" for c in job_id):
            return f"Error: invalid job_id '{job_id}'."

        job_dir = _working_root() / JOBS_DIR_NAME / _session_namespace() / job_id

        if not job_dir.exists() or not job_dir.is_dir():
            return f"Error: no job found with id '{job_id}'."

        output_file = job_dir / "output.log"
        exit_code_file = job_dir / "exit_code"

        raw_text, file_truncated, total_size = _read_capped(
            output_file, OUTPUT_READ_CAP_BYTES
        )
        text, char_truncated = _truncate(raw_text)
        truncated = file_truncated or char_truncated

        # A background job's output.log is bounded *at write time* on POSIX
        # via `head -c OUTPUT_CAP_BYTES` (see shell_exec_tool._spawn_background)
        # -- so a file sitting at exactly that size means the command's real
        # output was likely larger and got cut off. In that case the command
        # may also have been killed by SIGPIPE once `head` stopped reading,
        # so the recorded exit code may reflect that rather than the
        # command's own final exit status -- surface this explicitly instead
        # of reporting a bare, possibly-misleading exit code.
        background_output_capped = total_size >= OUTPUT_READ_CAP_BYTES

        parts = []
        if exit_code_file.exists():
            try:
                exit_code = exit_code_file.read_text(encoding="utf-8").strip()
            except Exception:
                exit_code = "unknown"
            if background_output_capped:
                parts.append(
                    "status: finished, but output reached the background "
                    f"output cap while running (recorded exit code: {exit_code} "
                    "-- may reflect SIGPIPE from the cap being hit rather than "
                    "the command's own final exit status)"
                )
            else:
                parts.append(f"status: finished (exit code: {exit_code})")
        else:
            parts.append("status: running")

        parts.append(f"output:\n{text}")

        if truncated:
            parts.append(
                f"(output truncated at {OUTPUT_CAP_CHARS} characters; "
                f"{total_size} total bytes produced so far)"
            )

        return "\n".join(parts)
    except Exception as e:
        return f"Error: failed to read job result. Unexpected exception: {e}"
