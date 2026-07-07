import sys

from conftest import load_tool_main

IS_WINDOWS = sys.platform.startswith("win")


def _echo_command(text: str) -> str:
    return f"echo {text}"


class TestShellJobResultToolValidation:
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


class TestShellJobResultToolSessionScoping:
    """job_id is namespaced under `.jobs/<session_id>/` (see
    shell_exec_tool._spawn_background) -- shell_job_result_tool must only
    ever resolve a job under the *caller's own* session_id global, so
    cross-session reads are impossible by construction rather than merely
    discouraged."""

    def test_resolves_job_started_under_own_session(self, sandbox_dir):
        exec_module = load_tool_main("shell_exec_tool")
        exec_module.session_id = 111

        start_result = exec_module.main(
            command=_echo_command("own-session"), run_in_background=True
        )
        job_id = start_result.split("job ")[1].split(".")[0]

        job_result_module = load_tool_main("shell_job_result_tool")
        job_result_module.session_id = 111

        result = job_result_module.main(job_id=job_id)

        assert not result.startswith("Error:")
        assert "own-session" in result or "status:" in result

    def test_cannot_resolve_another_sessions_job_id(self, sandbox_dir):
        exec_module = load_tool_main("shell_exec_tool")
        exec_module.session_id = 111

        start_result = exec_module.main(
            command=_echo_command("owner-only"), run_in_background=True
        )
        job_id = start_result.split("job ")[1].split(".")[0]

        # A different session (222) must not be able to read session 111's job,
        # even though the job_id itself is well-formed and does exist under
        # a different namespace on the same shared volume.
        job_result_module = load_tool_main("shell_job_result_tool")
        job_result_module.session_id = 222

        result = job_result_module.main(job_id=job_id)

        assert result.startswith("Error:")
        assert "no job found" in result

    def test_missing_session_id_falls_back_to_shared_nosession_namespace(
        self, sandbox_dir
    ):
        exec_module = load_tool_main("shell_exec_tool")
        # No session_id global set at all on either module -- both tools
        # must agree on the same fallback namespace so the flow still works
        # outside a crew-engine session context (dev/manual invocation).

        start_result = exec_module.main(
            command=_echo_command("no-session"), run_in_background=True
        )
        job_id = start_result.split("job ")[1].split(".")[0]

        job_result_module = load_tool_main("shell_job_result_tool")

        result = job_result_module.main(job_id=job_id)

        assert not result.startswith("Error:")

    def test_session_id_with_path_separators_is_rejected_and_sandboxed(
        self, sandbox_dir
    ):
        # A hostile/malformed session_id (path traversal attempt) must be
        # sanitized down to the shared fallback namespace rather than used
        # verbatim as a path component.
        exec_module = load_tool_main("shell_exec_tool")
        exec_module.session_id = "../../etc"

        start_result = exec_module.main(
            command=_echo_command("hostile-session"), run_in_background=True
        )
        job_id = start_result.split("job ")[1].split(".")[0]

        assert (sandbox_dir / ".jobs" / "_nosession" / job_id).is_dir()
        assert not (sandbox_dir / "etc").exists()

        job_result_module = load_tool_main("shell_job_result_tool")
        job_result_module.session_id = "../../etc"

        result = job_result_module.main(job_id=job_id)

        assert not result.startswith("Error:")

    def test_non_ascii_digit_session_id_falls_back_to_nosession_namespace(
        self, sandbox_dir
    ):
        # "²" (superscript two) is accepted by str.isdigit() but is not an
        # ASCII digit -- must not be trusted verbatim as a path component.
        exec_module = load_tool_main("shell_exec_tool")
        exec_module.session_id = "²³"

        start_result = exec_module.main(
            command=_echo_command("non-ascii-session"), run_in_background=True
        )
        job_id = start_result.split("job ")[1].split(".")[0]

        assert (sandbox_dir / ".jobs" / "_nosession" / job_id).is_dir()
        assert not (sandbox_dir / ".jobs" / "²³").exists()

        job_result_module = load_tool_main("shell_job_result_tool")
        job_result_module.session_id = "²³"

        result = job_result_module.main(job_id=job_id)

        assert not result.startswith("Error:")


class TestShellJobResultToolBoundedRead:
    def test_oversized_output_file_is_read_with_a_bounded_cap(self, sandbox_dir):
        """Simulates a job whose output.log on disk is already far bigger
        than the char cap -- shell_job_result_tool must not `read_text()`
        the whole file into memory; it should read at most a bounded number
        of bytes and still report the correct truncation + total size.

        The job directory is built directly (rather than via a real
        shell_exec_tool background job) so the oversized file content is
        deterministic -- a live background process could still be writing
        to output.log at the moment of inspection.
        """
        job_id = "a" * 32
        job_dir = sandbox_dir / ".jobs" / "999" / job_id
        job_dir.mkdir(parents=True)
        # "q" deliberately avoids colliding with letters in the tool's own
        # status/truncation message text (e.g. "y" appears in "bytes").
        (job_dir / "output.log").write_text("q" * 500_000, encoding="utf-8")
        (job_dir / "exit_code").write_text("0", encoding="utf-8")

        job_result_module = load_tool_main("shell_job_result_tool")
        job_result_module.session_id = 999

        result = job_result_module.main(job_id=job_id)

        assert "truncated at 30000 characters" in result
        assert "500000 total bytes produced so far" in result
        # The displayed output itself must be capped at OUTPUT_CAP_CHARS,
        # not the full 500000-char file.
        assert result.count("q") <= 30000

    def test_background_output_at_the_cap_surfaces_sigpipe_caveat(self, sandbox_dir):
        """A background job's output.log is bounded at write time by `head -c`
        (shell_exec_tool._spawn_background). When the file sits at (or past)
        that cap, the command's own output was likely larger and it may have
        been killed by SIGPIPE -- shell_job_result_tool must surface this
        explicitly rather than reporting a bare, possibly-misleading exit
        code (Critical fix: previously a background job hitting the cap
        looked identical to an ordinary small job that exited cleanly)."""
        job_id = "b" * 32
        job_dir = sandbox_dir / ".jobs" / "999" / job_id
        job_dir.mkdir(parents=True)
        job_result_module = load_tool_main("shell_job_result_tool")
        (job_dir / "output.log").write_text(
            "q" * job_result_module.OUTPUT_READ_CAP_BYTES, encoding="utf-8"
        )
        # 141 == 128 + SIGPIPE(13), the exit status a subshell reports when
        # killed by SIGPIPE after `head` stops reading.
        (job_dir / "exit_code").write_text("141", encoding="utf-8")

        job_result_module.session_id = 999

        result = job_result_module.main(job_id=job_id)

        assert "reached the background" in result
        assert "SIGPIPE" in result
        assert "recorded exit code: 141" in result
        # Must not look like an ordinary clean-exit status line.
        assert "status: finished (exit code:" not in result

    def test_small_output_file_is_not_marked_truncated(self, sandbox_dir):
        exec_module = load_tool_main("shell_exec_tool")
        exec_module.session_id = 1

        start_result = exec_module.main(
            command=_echo_command("small"), run_in_background=True
        )
        job_id = start_result.split("job ")[1].split(".")[0]

        job_result_module = load_tool_main("shell_job_result_tool")
        job_result_module.session_id = 1

        import time

        deadline = time.time() + 10
        result = ""
        while time.time() < deadline:
            result = job_result_module.main(job_id=job_id)
            if "finished" in result:
                break
            time.sleep(0.2)

        assert "truncated" not in result
        assert "small" in result
