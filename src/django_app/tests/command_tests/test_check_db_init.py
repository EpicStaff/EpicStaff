"""check_db_init waits for Postgres, retrying until it accepts a connection."""

from types import SimpleNamespace

import pytest
from django.core.management import call_command
from django.db import connection

from django_app.settings import env

ATTEMPTS = 150


@pytest.fixture
def recorded_sleeps(monkeypatch):
    sleeps = []
    monkeypatch.setattr(
        "tables.management.commands.check_db_init.time", SimpleNamespace(sleep=sleeps.append)
    )
    return sleeps


@pytest.mark.django_db
def test_returns_as_soon_as_postgres_accepts_a_connection(monkeypatch, recorded_sleeps):
    monkeypatch.setitem(env._envs, "DB_NAME", connection.settings_dict["NAME"])

    call_command("check_db_init")

    assert recorded_sleeps == []


@pytest.mark.django_db
def test_retries_while_postgres_refuses_then_gives_up(monkeypatch, recorded_sleeps):
    monkeypatch.setitem(env._envs, "DB_NAME", "database_that_does_not_exist")

    with pytest.raises(RuntimeError, match="Postgres is not ready"):
        call_command("check_db_init")

    assert recorded_sleeps == [2] * ATTEMPTS
