from importlib import import_module
from pathlib import Path

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from rbac.models import ApiKey, Organization, OrganizationUser, Role
from rbac.identity.api_keys.generator import ApiKeyGenerator

# Import shared fixtures (graph, agent, session_data, etc.)
from .fixtures import *  # noqa: F401,F403


class _MovedModelApps:
    """Lets migration seed functions, written when these models lived in `tables`,
    resolve them now that they live in `rbac`.

    The migrations themselves are correct: during a real replay `apps` is the
    historical ProjectState, where these models really were in `tables`. Only this
    out-of-band replay against the live registry needs the redirect.
    """

    _MOVED = frozenset(
        {
            "role",
            "rolepermission",
            "organization",
            "organizationuser",
            "apikey",
            "passwordresettoken",
        }
    )

    def get_model(self, app_label, model_name):
        if app_label == "tables" and model_name.lower() in self._MOVED:
            app_label = "rbac"
        return django_apps.get_model(app_label, model_name)


def seed_builtin_roles_and_permissions() -> None:
    """Re-run every data migration that seeds built-in Roles/RolePermissions.

    `flush` wipes them; in production they are written once by the migrations
    and never touched. This is the single authoritative chain -- both the
    session flush below and `heal_builtin_roles` call it, so there is one
    definition of the seeded end state and no way for the two to disagree.

    Replayed in migration order, because later ones override earlier ones:

      0171  roles + initial bitmasks
      0183  authoritative bitmasks (e.g. Org Admin export on agents/projects)
      0205  surfaces grants
      0209  Org Admin organizations = READ|UPDATE
      0210  rename resource_type `users` -> `memberships`
      0210  voice bitmasks, and the EXPORT bit on tools
      0212  Org Admin api_keys = READ|DELETE
      0236  revoke secrets:USE from Member/Viewer (192 -> 128)
      0242  re-seed all three roles to the masks the code enforces
      0245  grant Org Admin knowledge_sources:EXPORT (for document download)
      0246  seed the `webhooks` resource permissions

    Order is load-bearing twice over. The rename must precede 0242, which
    writes `memberships` rows directly -- running it first would leave both a
    `users` and a `memberships` row per role and the rename would then trip
    the (role, resource_type) unique constraint. And 0242 must precede any
    subsequent additive seed: 0242 is the authoritative baseline and drops
    bits the earlier seeds write (flows:USE on Viewer, secrets:LIST,
    secrets:UPDATE); a later seed layers additional grants on top.

    Skipping any step leaves tests on stale permissions -- e.g. without the
    voice seed every non-superadmin request to a VOICE-gated endpoint 403s in
    tests although the migration seeds it correctly in production.

    Migration module names start with digits and cannot be imported with
    `from ... import`; use importlib.
    """
    steps = [
        ("tables.migrations.0171_seed_builtin_roles", "seed_builtin_roles"),
        (
            "tables.migrations.0183_seed_builtin_role_permissions",
            "seed_role_permissions",
        ),
        ("tables.migrations.0205_seed_surface_permissions", "seed"),
        (
            "tables.migrations.0209_seed_org_admin_organizations_perm",
            "seed_org_admin_organizations_perm",
        ),
        (
            "tables.migrations.0210_alter_rolepermission_resource_type",
            "rename_users_to_memberships",
        ),
        (
            "tables.migrations.0210_seed_voice_role_permissions",
            "seed_voice_permissions",
        ),
        ("tables.migrations.0210_seed_tools_export_permission", "grant_tools_export"),
        (
            "tables.migrations.0212_alter_rolepermission_resource_type",
            "seed_org_admin_api_keys_perm",
        ),
        ("tables.migrations.0236_secrets_use_permission", "revoke_builtin_use"),
        (
            "tables.migrations.0242_reseed_builtin_role_permissions",
            "reseed_builtin_role_permissions",
        ),
        (
            "tables.migrations.0245_knowledge_sources_export_permission",
            "grant_knowledge_sources_export",
        ),
        (
            "tables.migrations.0246_seed_webhooks_resource_permissions",
            "seed_webhooks_permissions",
        ),
    ]
    moved_model_apps = _MovedModelApps()
    for module_path, func_name in steps:
        getattr(import_module(module_path), func_name)(moved_model_apps, None)


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
    runs, then replay the seeds that `flush` wipes.

    The replay is `seed_builtin_roles_and_permissions()` and nothing else --
    it is the single authoritative chain. This fixture used to re-run a subset
    of the migrations after it, which both duplicated the definition and, once
    0242 landed, would have re-written the bits 0242 exists to remove.
    """
    with django_db_blocker.unblock():
        call_command("flush", "--noinput")
        seed_builtin_roles_and_permissions()


@pytest.fixture(autouse=True)
def heal_builtin_roles(request):
    """Make sure the built-in Roles exist before every database test.

    A `django_db(transaction=True)` test truncates every table at teardown,
    including the built-in Roles that `flush_test_db_once` seeds once per
    session. That damage cannot be repaired by the offending test: fixture
    teardown is LIFO, and pytest-django's transactional helper is set up
    before anything the test itself requests, so its flush always runs
    *last*. Healing at setup time is therefore the only order-independent
    place to do it.

    Cheap in the common case — one EXISTS query when the rows are present.
    Skipped entirely for tests that never touch the database, so it cannot
    trigger database setup for a pure unit test.
    """
    touches_db = request.node.get_closest_marker("django_db") is not None or bool(
        {"db", "transactional_db"} & set(request.fixturenames)
    )
    if not touches_db:
        return
    if not Role.objects.filter(is_built_in=True).exists():
        seed_builtin_roles_and_permissions()


@pytest.fixture(autouse=True)
def clear_default_models_cache():
    from tables.models.base_models import DefaultBaseModel

    DefaultBaseModel._load_cache.clear()
    yield
    DefaultBaseModel._load_cache.clear()


@pytest.fixture
def fake_async_redis():
    """Fresh in-memory async Redis client, the one `patch_graph_state_redis` installs.

    Request it by name to pre-seed or inspect live collab state, or to share it
    with another patched client (see `patch_redis_service` in
    tests/graph_collab/conftest.py). `decode_responses=True` matches
    `RedisService.async_redis_client`.
    """
    import fakeredis.aioredis

    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture(autouse=True)
def patch_graph_state_redis(fake_async_redis, monkeypatch):
    """Point graph_state_service at `fake_async_redis` and reset its in-memory state.

    Graph save, version create/restore, run-session and the collab consumer all
    read or write the live collab snapshot through `graph_state_service._redis`.
    The real client is a cached `redis.asyncio` client bound to the first event
    loop that used it, so a sync test that reaches it through `async_to_sync`
    fails with "Event loop is closed". Autouse, so every test that reaches the
    service gets the fake without asking for it.

    Patches only `GraphLiveStateService._redis`. Every other Redis client
    (`RedisService`, pub/sub, channel layers) is left alone.
    """
    from tables.graph_collab import graph_state_service as graph_state_service_module

    live_state_service = graph_state_service_module.graph_state_service
    monkeypatch.setattr(
        type(live_state_service),
        "_redis",
        property(lambda self: fake_async_redis),
    )
    # The revision counters describe the snapshot in Redis; a fresh fake Redis
    # with counters left over from an earlier test would report a wrong dirty state.
    # The per-graph asyncio locks are dropped too, so no test reuses a lock bound
    # to an earlier test's event loop.
    _reset_live_state_memory(live_state_service)
    yield
    _reset_live_state_memory(live_state_service)


def _reset_live_state_memory(live_state_service) -> None:
    live_state_service._locks.clear()
    live_state_service._revision.clear()
    live_state_service._flushed_revision.clear()


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
    org, _ = Organization.objects.get_or_create(name="Default Organization")
    return org


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
    # fixtures (graph/agent) are created in the same org, so sending the
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
def superadmin_client_with_org(
    api_client, superadmin_jwt_tokens, default_org
) -> APIClient:
    """Superadmin client with an active-org header set.

    `OrgContextService` requires the `X-Organization-Id` header on every
    request even for a superadmin caller — it only skips the *membership*
    check for superadmins, not the header itself. Endpoints that call
    `get_active_org_id()`/`OrgContextService.resolve()` unconditionally
    (e.g. cross-org storage transfers, which resolve an active org even
    though the actual source/destination orgs come from the payload) need
    this over plain `superadmin_client`.
    """
    api_client.credentials(
        HTTP_AUTHORIZATION=f"Bearer {superadmin_jwt_tokens['access']}",
        HTTP_X_ORGANIZATION_ID=str(default_org.id),
    )
    return api_client


@pytest.fixture
def issue_api_key(db):
    """Factory: create an ApiKey directly (bypasses endpoint/cap) and
    return (raw_key, ApiKey). user=None + key_type=SYSTEM makes a system key."""

    def _issue(user=None, **overrides):
        generated = ApiKeyGenerator.generate()
        key = ApiKey.objects.create(
            name=overrides.pop("name", "test-key"),
            key_type=overrides.pop(
                "key_type",
                ApiKey.KeyType.USER if user else ApiKey.KeyType.SYSTEM,
            ),
            prefix=generated.prefix,
            key_hash=generated.key_hash,
            created_by=user,
            **overrides,
        )
        return generated.raw_key, key

    return _issue


@pytest.fixture
def env_api_key(issue_api_key):
    return issue_api_key(user=None, name="env-system")


@pytest.fixture
def user_api_key(regular_user, issue_api_key):
    return issue_api_key(user=regular_user, name="user-key")
