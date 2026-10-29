"""Behavior of the child environment builder and the privilege drop helpers.

``build_base_env`` deliberately does not inherit ``os.environ``. The exact key set is
asserted, so adding a variable to it has to be a deliberate change -- that is the
regression guard against the worker's own credentials leaking into user code.
"""

import os
from pathlib import Path

from worker.infrastructure.execution import privileges
from worker.infrastructure.execution.environment import build_base_env


def test_the_base_environment_has_exactly_the_curated_keys():
    env = build_base_env("/venvs/venv-1abc/bin/python")

    assert set(env) == {
        "LANG",
        "PYTHONUTF8",
        "PYTHONUNBUFFERED",
        "PYTHONDONTWRITEBYTECODE",
        "PATH",
    }


def test_the_path_starts_with_the_venv_bin_directory():
    env = build_base_env("/venvs/venv-1abc/bin/python")

    assert env["PATH"].split(os.pathsep) == [
        "/venvs/venv-1abc/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]


def test_the_base_environment_does_not_inherit_the_worker_environment(monkeypatch):
    monkeypatch.setenv("SANDBOX_DB_PASSWORD", "do-not-leak")

    env = build_base_env("/venvs/venv-1abc/bin/python")

    assert "SANDBOX_DB_PASSWORD" not in env
    assert "do-not-leak" not in str(env)


def test_a_path_object_is_accepted():
    env = build_base_env(Path("/venvs/venv-1abc/bin/python"))

    assert env["PATH"].startswith("/venvs/venv-1abc/bin")


def test_privileges_can_be_dropped_only_as_root(monkeypatch):
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 0)
    assert privileges.can_drop_privileges() is True

    monkeypatch.setattr(privileges.os, "geteuid", lambda: 1000)
    assert privileges.can_drop_privileges() is False


def test_a_non_root_worker_passes_no_privilege_kwargs(monkeypatch):
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 1000)

    assert privileges.privilege_drop_kwargs() == {}


def test_a_root_worker_drops_the_child_to_the_sandbox_user(monkeypatch):
    monkeypatch.setattr(privileges.os, "geteuid", lambda: 0)

    assert privileges.privilege_drop_kwargs() == {
        "user": privileges.SANDBOX_UID,
        "group": privileges.SANDBOX_GID,
        "extra_groups": [],
    }
