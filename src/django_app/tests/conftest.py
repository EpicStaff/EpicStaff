from pathlib import Path
import pytest
from django.core.management import call_command
from rest_framework.test import APIClient

# Import shared fixtures (graph, crew, session_data, etc.)
from .fixtures import *  # noqa: F401,F403


@pytest.fixture(scope="session", autouse=True)
def flush_test_db_once(django_db_setup, django_db_blocker):
    """Flush the test DB once per session to remove stale data from previous
    runs, then re-run the data-migration seed functions that `flush` wipes
    (built-in Roles). In production these are seeded once by migration 0171
    and never touched; `flush` doesn't discriminate, so we have to re-apply."""
    from importlib import import_module

    from django.apps import apps as django_apps

    with django_db_blocker.unblock():
        call_command("flush", "--noinput")
        # Migration module names start with digits and cannot be imported via
        # `from ... import`; use importlib. Delegating to the migration's own
        # seed function keeps the role list defined in exactly one place.
        seed_module = import_module("tables.migrations.0171_seed_builtin_roles")
        seed_module.seed_builtin_roles(django_apps, None)


@pytest.fixture
def resources_path():
    return Path("./tests/resources/").resolve()


@pytest.fixture
def tmp_path():
    return Path("./tests/tmp/").resolve()


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture
def mock_telegram_service(mocker):
    return mocker.patch(
        "tables.services.telegram_trigger_service.TelegramTriggerService.register_telegram_trigger"
    )
