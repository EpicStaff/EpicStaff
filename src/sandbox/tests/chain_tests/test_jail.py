"""Unit coverage for build_jail(): a pure allowlist builder, no chain, no Redis."""

import dataclasses
from pathlib import Path

import pytest

from jail import Jail, build_jail


def _jail() -> Jail:
    return build_jail(
        exec_dir=Path("/app/src/sandbox/executions/exec-1"),
        venv_path=Path("/app/src/sandbox/venvs/somehash"),
        savefiles_root=Path("/app/src/sandbox/savefiles"),
    )


class TestBuildJail:
    def test_every_returned_path_is_absolute(self):
        jail = _jail()

        for path in (*jail.read_write, *jail.read_only, *jail.read_exec):
            assert Path(path).is_absolute(), path

    def test_exec_dir_and_its_subdirs_are_read_write(self):
        jail = _jail()

        assert "/app/src/sandbox/executions/exec-1" in jail.read_write
        assert "/app/src/sandbox/executions/exec-1/home" in jail.read_write
        assert "/app/src/sandbox/executions/exec-1/tmp" in jail.read_write

    def test_savefiles_root_is_read_write(self):
        jail = _jail()

        assert "/app/src/sandbox/savefiles" in jail.read_write

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
            Path("/app/src/sandbox/savefiles"),
        }

        for path in (*jail.read_write, *jail.read_only, *jail.read_exec):
            entry = Path(path)
            assert entry != forbidden_source_dir
            if entry == forbidden_source_dir or forbidden_source_dir in entry.parents:
                assert entry in allowed_subpaths or any(
                    allowed in entry.parents or entry == allowed
                    for allowed in allowed_subpaths
                )

    def test_jail_is_frozen(self):
        jail = _jail()

        with pytest.raises(dataclasses.FrozenInstanceError):
            jail.read_write = ()
