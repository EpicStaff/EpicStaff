from pathlib import Path
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from tables.models.rbac_models import ApiKey, Organization, OrganizationUser, Role

# Import shared fixtures (graph, crew, session_data, etc.)
from .fixtures import *  # noqa: F401,F403


def _seed_builtin_roles() -> None:
    """Re-run the data-migration seed functions for built-in Roles. In
    production these are seeded once by migration 0171 (+ 0183 for
    permission bitmasks) and never touched; test-DB `flush` and
    `transaction=True` test teardowns wipe them, so callers re-apply this
    to restore a consistent baseline. Both seed functions are idempotent
    (get_or_create / update_or_create), so re-running them is safe."""
    from importlib import import_module

    from django.apps import apps as django_apps

    # Migration module names start with digits and cannot be imported via
    # `from ... import`; use importlib. Delegating to the migrations' own
    # seed functions keeps the role/permission definitions in one place.
    # Replay BOTH seeds in migration order: 0171 seeds roles + initial
    # permission bitmasks, then 0183 overrides them with the authoritative
    # bitmasks (e.g. Org Admin export on agents/projects). Re-seeding only
    # 0171 would leave tests on the stale pre-0183 permissions.
    roles_module = import_module("tables.migrations.0171_seed_builtin_roles")
    roles_module.seed_builtin_roles(django_apps, None)
    perms_module = import_module("tables.migrations.0183_seed_builtin_role_permissions")
    perms_module.seed_role_permissions(django_apps, None)


def _get_test_db_name() -> str:
    from django.db import connection

    return connection.creation._get_test_db_name()


def _maintenance_connection():
    """Open an autocommit connection to the `postgres` maintenance DB using
    the same credentials as the `default` Django DB, so we can terminate
    backends / drop the test DB from outside of it."""
    import psycopg2
    from django.conf import settings

    db_settings = settings.DATABASES["default"]
    conn = psycopg2.connect(
        dbname="postgres",
        user=db_settings["USER"],
        password=db_settings["PASSWORD"],
        host=db_settings["HOST"],
        port=db_settings["PORT"],
    )
    conn.autocommit = True
    return conn


def _terminate_test_db_backends(test_db_name: str) -> None:
    """Terminate any lingering backend connections to `test_db_name`. Safe to
    call even if the DB doesn't exist or has no connections."""
    conn = _maintenance_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = %s AND pid <> pg_backend_pid()",
                (test_db_name,),
            )
    finally:
        conn.close()


def _force_drop_test_db(test_db_name: str) -> None:
    """Terminate lingering backends then drop `test_db_name` if present.
    Used before test-DB creation to clear a stale DB left behind by a
    previous run that was killed mid-session (Blocker A)."""
    import psycopg2
    from psycopg2 import sql

    _terminate_test_db_backends(test_db_name)
    conn = _maintenance_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                sql.SQL("DROP DATABASE IF EXISTS {}").format(
                    sql.Identifier(test_db_name)
                )
            )
    finally:
        conn.close()


@pytest.fixture(scope="session")
def django_db_setup(
    request,
    django_test_environment,  # noqa: ARG001
    django_db_blocker,
    django_db_use_migrations,
    django_db_keepdb,
    django_db_createdb,
    django_db_modify_db_settings,  # noqa: ARG001
):
    """Override pytest-django's default `django_db_setup` to add two pieces
    of test-infra robustness around the (single) `test_crew` database:

    Blocker A: if a previous pytest run was killed mid-session, pytest-django
    never gets to drop `test_crew`, so the next run's `CREATE DATABASE` fails.
    Fix: force-terminate any lingering backends and drop `test_crew` (if it
    exists) BEFORE delegating to `setup_databases()`.

    Blocker B safety net: the plain `DROP DATABASE` in `teardown_databases()`
    hangs forever if any connection to `test_crew` is still open at session
    end. Fix: close all Django connections and terminate any remaining
    Postgres backends for `test_crew` right before teardown, so the DROP
    can't block. (The actual leaked-connection root cause — two tests never
    calling `communicator.disconnect()` — is fixed at the call sites; this is
    only a safety net for any other future leak.)
    """
    from django.db import connections
    from django.test.utils import setup_databases, teardown_databases
    from pytest_django.fixtures import _disable_migrations

    if not django_db_use_migrations:
        _disable_migrations()

    setup_databases_args = {}
    if django_db_keepdb and not django_db_createdb:
        setup_databases_args["keepdb"] = True

    with django_db_blocker.unblock():
        test_db_name = _get_test_db_name()
        _force_drop_test_db(test_db_name)
        db_cfg = setup_databases(
            verbosity=request.config.option.verbose,
            interactive=False,
            **setup_databases_args,
        )

    yield

    if not django_db_keepdb:
        with django_db_blocker.unblock():
            connections.close_all()
            _terminate_test_db_backends(test_db_name)
            try:
                teardown_databases(db_cfg, verbosity=request.config.option.verbose)
            except Exception as exc:  # noqa: BLE001
                request.node.warn(
                    pytest.PytestWarning(
                        f"Error when trying to teardown test databases: {exc!r}"
                    )
                )


@pytest.fixture(scope="session", autouse=True)
def flush_test_db_once(django_db_setup, django_db_blocker):
    """Flush the test DB once per session to remove stale data from previous
    runs, then re-seed the built-in Roles that `flush` wipes."""
    with django_db_blocker.unblock():
        call_command("flush", "--noinput")
        _seed_builtin_roles()


@pytest.fixture(autouse=True)
def reseed_builtin_roles_for_db_tests(request):
    """Re-seed built-in Roles before every test that actually touches the
    DB. `@pytest.mark.django_db(transaction=True)` tests truncate all tables
    (including the session-seeded Roles) on teardown, so later RBAC tests in
    the same session would otherwise find Roles empty. This must stay a
    no-op for pure unit tests that don't request the DB at all — requesting
    `db`/`transactional_db` unconditionally would force DB setup on tests
    that never asked for it."""
    db_fixture_names = {"db", "transactional_db", "django_db_reset_sequences"}
    uses_db = bool(db_fixture_names & set(request.fixturenames)) or (
        request.node.get_closest_marker("django_db") is not None
    )
    if not uses_db:
        return

    for fixture_name in db_fixture_names:
        if fixture_name in request.fixturenames:
            request.getfixturevalue(fixture_name)
            break
    else:
        # `django_db` marker present but none of the DB fixtures were
        # explicitly requested — pull in the plain `db` fixture ourselves.
        request.getfixturevalue("db")

    _seed_builtin_roles()


@pytest.fixture(autouse=True)
def clear_default_models_cache():
    from tables.models.base_models import DefaultBaseModel

    DefaultBaseModel._load_cache.clear()
    yield
    DefaultBaseModel._load_cache.clear()


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


# -----------------------------------
# RBAC
# -----------------------------------
@pytest.fixture
def superadmin_user(db):
    return get_user_model().objects.create_superuser(
        email="superadmin@example.com",
        password="SuperStrongPass123!",
    )


@pytest.fixture
def default_org(db):
    return Organization.objects.create(name="Default Organization")


@pytest.fixture
def org_admin_role(db):
    return Role.objects.get(name="Org Admin", is_built_in=True, org__isnull=True)


@pytest.fixture
def regular_user(db, default_org, org_admin_role):
    user = get_user_model().objects.create_user(
        email="user@example.com",
        password="UserStrongPass123!",
    )
    OrganizationUser.objects.create(user=user, org=default_org, role=org_admin_role)
    return user


@pytest.fixture
def jwt_tokens(regular_user):
    refresh = RefreshToken.for_user(regular_user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@pytest.fixture
def auth_client(api_client, jwt_tokens, default_org) -> APIClient:
    # regular_user is an Org Admin member of default_org; the shared resource
    # fixtures (graph/agent/crew) are created in the same org, so sending the
    # active-org header makes org-scoped endpoints resolve and authorize.
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {jwt_tokens['access']}",
        HTTP_X_ORGANIZATION_ID=str(default_org.id),
    )
    return api_client


@pytest.fixture
def superadmin_jwt_tokens(superadmin_user):
    refresh = RefreshToken.for_user(superadmin_user)
    return {"access": str(refresh.access_token), "refresh": str(refresh)}


@pytest.fixture
def superadmin_client(api_client, superadmin_jwt_tokens) -> APIClient:
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {superadmin_jwt_tokens['access']}"
    )
    return api_client


@pytest.fixture
def env_api_key(db):
    raw = ApiKey.generate_raw_key()
    key = ApiKey(name="env-system")
    key.set_key(raw)
    key.save()
    return raw, key


@pytest.fixture
def user_api_key(regular_user):
    raw = ApiKey.generate_raw_key()
    key = ApiKey(name="user-key", created_by=regular_user)
    key.set_key(raw)
    key.save()
    return raw, key
