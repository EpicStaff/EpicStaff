"""manage.py exits non-zero when a command fails, so entrypoint.sh (set -e) stops startup."""

from types import SimpleNamespace

import pytest

import manage
from django_app.settings import env


def test_command_raising_a_non_command_error_exits_with_status_one(monkeypatch):
    monkeypatch.setitem(env._envs, "DB_NAME", "database_that_does_not_exist")
    monkeypatch.setattr(
        "tables.management.commands.check_db_init.time", SimpleNamespace(sleep=lambda seconds: None)
    )
    monkeypatch.setattr("sys.argv", ["manage.py", "check_db_init"])

    with pytest.raises(SystemExit) as exit_info:
        manage.main()

    assert exit_info.value.code == 1
