"""Unit coverage for build_jail(): a pure allowlist builder, no chain, no Redis."""

import os
from pathlib import Path

import pytest

from jail import Jail, build_jail

_posix_only = pytest.mark.skipif(
    os.name != "posix",
    reason="POSIX-only: build_jail's absolute-path semantics (leading '/') only hold on POSIX; Path resolves them differently on Windows",
)


def _jail() -> Jail:
    return build_jail(
        exec_dir=Path("/app/src/sandbox/executions/exec-1"),
        venv_path=Path("/app/src/sandbox/venvs/somehash"),
    )


class TestBuildJail:
    @_posix_only
    def test_every_returned_path_is_absolute(self):
        jail = _jail()

        for path in (*jail.read_write, *jail.read_only, *jail.read_exec):
            assert Path(path).is_absolute(), path

    @_posix_only
    def test_only_the_runs_own_exec_dir_and_its_subdirs_are_read_write(self):
        jail = _jail()

        assert jail.read_write == (
            "/app/src/sandbox/executions/exec-1",
            "/app/src/sandbox/executions/exec-1/home",
            "/app/src/sandbox/executions/exec-1/tmp",
        )

    @_posix_only
    def test_venv_path_is_read_exec_and_not_read_write(self):
        jail = _jail()

        assert "/app/src/sandbox/venvs/somehash" in jail.read_exec
        assert "/app/src/sandbox/venvs/somehash" not in jail.read_write

    def test_app_root_itself_is_not_an_entry(self):
        jail = _jail()

        for path in (*jail.read_write, *jail.read_only, *jail.read_exec):
            assert path != "/app"

    def test_sandbox_source_directory_is_not_reachable(self):
        """The sandbox's own source at /app/src/sandbox must not be granted as a
        whole, or user code could read/modify the code that runs it. Only the
        two specific subpaths this execution actually needs -- its own exec
        dir and the venv -- may appear under /app/src/sandbox."""
        jail = _jail()
        forbidden_source_dir = Path("/app/src/sandbox")
        allowed_subpaths = {
            Path("/app/src/sandbox/executions/exec-1"),
            Path("/app/src/sandbox/venvs/somehash"),
        }

        for path in (*jail.read_write, *jail.read_only, *jail.read_exec):
            entry = Path(path)
            assert entry != forbidden_source_dir
            if entry == forbidden_source_dir or forbidden_source_dir in entry.parents:
                assert entry in allowed_subpaths or any(
                    allowed in entry.parents or entry == allowed
                    for allowed in allowed_subpaths
                )
