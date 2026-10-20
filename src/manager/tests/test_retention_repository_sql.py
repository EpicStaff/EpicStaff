"""RetentionRepository against a dedicated crewdb test database.

The database is ``<DB_NAME>_test`` on the crewdb server, never the developer's own: the
session refuses any other name. Its schema is Django's, so the first run (and any run after
a new Django migration) builds it with ``make django-migrate`` against that name; later runs
only compare the migration files with ``django_migrations``. The manager role's grants are
then applied from src/crewdb/custom-docker-entrypoint.sh, as the container does.

Rows are committed, so a second connection can hold locks, and each test starts by deleting
what these tests create. Skipped when crewdb is unreachable.
"""

import asyncio
import os
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import asyncpg
import pytest
import pytest_asyncio
import settings
from helpers.logger import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from repositories.retention_repository import (
    OrgRetentionRow,
    RetentionInterruptedError,
    RetentionRepository,
)
from src.shared.retention import SESSION_CHILD_TABLES
from tests.crewdb_entrypoint import grant_manager_sql

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
TEST_DATABASE = f"{settings.DB_NAME}_test"
SUPERUSER = settings.env.str("DB_USER")
SUPERUSER_PASSWORD = settings.env.str("DB_PASSWORD")
MANAGER_ROLE = settings.DB_USER
TEST_ORG_PREFIX = "retention-test-"

CUTOFF = datetime(2026, 9, 20, 3, 30, tzinfo=UTC)
EXPIRED = CUTOFF - timedelta(days=10)
RECENT = CUTOFF + timedelta(days=25)

_CLEANUP = [
    *(f"DELETE FROM {link.table}" for link in SESSION_CHILD_TABLES),
    "DELETE FROM tables_keyvaluetableentry",
    "DELETE FROM tables_keyvaluetable",
    "DELETE FROM tables_session",
    "DELETE FROM tables_storagefile",
    "DELETE FROM rbac_organization_retention",
    "DELETE FROM tables_graph",
    f"DELETE FROM rbac_organization WHERE name LIKE '{TEST_ORG_PREFIX}%'",
]


def _refuse_non_test_database(name: str) -> None:
    if not name.endswith("_test"):
        pytest.exit(f"Refusing to run retention SQL tests against {name!r}: not a *_test database.")


def _pending_django_migrations(applied: set[tuple[str, str]]) -> list[str]:
    # A squashed migration is recorded under the names it replaces, never its own.
    files = (REPOSITORY_ROOT / "src" / "django_app").glob("*/migrations/[0-9]*.py")
    return sorted(
        f"{path.parent.parent.name}.{path.stem}"
        for path in files
        if "_squashed_" not in path.stem and (path.parent.parent.name, path.stem) not in applied
    )


def _migrate_test_database() -> None:
    environment = {**os.environ, "DB_NAME": TEST_DATABASE}
    completed = subprocess.run(
        ["make", "django-migrate"],
        cwd=REPOSITORY_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        pytest.fail(
            f"make django-migrate for {TEST_DATABASE} failed:\n"
            f"{completed.stdout[-3000:]}\n{completed.stderr[-3000:]}"
        )


async def _prepare_test_database() -> bool:
    """Create, migrate and grant the test database; return whether the manager role exists."""

    async def connect(database: str) -> asyncpg.Connection:
        return await asyncpg.connect(
            host=settings.DB_HOST,
            port=int(settings.DB_PORT),
            user=SUPERUSER,
            password=SUPERUSER_PASSWORD,
            database=database,
            timeout=3,
        )

    try:
        admin = await connect("postgres")
    except (OSError, asyncpg.PostgresError) as error:
        pytest.skip(f"crewdb is unreachable: {error}")
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DATABASE):
            await admin.execute(f'CREATE DATABASE "{TEST_DATABASE}"')
        role_exists = bool(
            await admin.fetchval("SELECT 1 FROM pg_roles WHERE rolname = $1", MANAGER_ROLE)
        )
    finally:
        await admin.close()

    connection = await connect(TEST_DATABASE)
    try:
        applied = set()
        if await connection.fetchval("SELECT to_regclass('django_migrations') IS NOT NULL"):
            applied = {
                (row["app"], row["name"])
                for row in await connection.fetch("SELECT app, name FROM django_migrations")
            }
    finally:
        await connection.close()
    if _pending_django_migrations(applied):
        _migrate_test_database()

    if role_exists:
        connection = await connect(TEST_DATABASE)
        try:
            await connection.execute(grant_manager_sql(MANAGER_ROLE))
        finally:
            await connection.close()
    return role_exists


@pytest.fixture(scope="session")
def manager_role_exists() -> bool:
    _refuse_non_test_database(TEST_DATABASE)
    return asyncio.run(_prepare_test_database())


def _engine(user: str, password: str):
    return create_async_engine(
        f"postgresql+asyncpg://{user}:{password}@{settings.DB_HOST}:{settings.DB_PORT}/{TEST_DATABASE}"
    )


@pytest_asyncio.fixture
async def engine(manager_role_exists):
    engine = _engine(SUPERUSER, SUPERUSER_PASSWORD)
    async with engine.begin() as connection:
        _refuse_non_test_database(await connection.scalar(text("SELECT current_database()")))
        for statement in _CLEANUP:
            await connection.execute(text(statement))
    yield engine
    await engine.dispose()


@pytest.fixture
def repository(engine):
    return RetentionRepository(async_sessionmaker(engine, expire_on_commit=False))


class Database:
    """Commits the rows a test needs, filling the NOT NULL columns Django leaves to Python."""

    def __init__(self, engine):
        self.engine = engine

    async def execute(self, sql: str, **params):
        async with self.engine.begin() as connection:
            return await connection.execute(text(sql), params)

    async def value(self, sql: str, **params):
        return (await self.execute(sql, **params)).scalar()

    async def org(self, sessions_days=None, with_retention_row=False) -> int:
        org_id = await self.value(
            "INSERT INTO rbac_organization (name, is_active, is_default, created_at, updated_at) "
            "VALUES (:name, true, false, now(), now()) RETURNING id",
            name=f"{TEST_ORG_PREFIX}{uuid.uuid4()}",
        )
        if with_retention_row:
            await self.execute(
                "INSERT INTO rbac_organization_retention "
                "(org_id, sessions_days, conversations_days, audit_days, updated_at) "
                "VALUES (:org_id, :sessions_days, 90, NULL, now())",
                org_id=org_id,
                sessions_days=sessions_days,
            )
        return org_id

    async def graph(self, org_id: int, in_recycle_bin: bool = False) -> int:
        return await self.value(
            "INSERT INTO tables_graph (name, metadata, description, time_to_live, "
            "enable_persistent_variables, created_at, updated_at, epicchat_enabled, uuid, org_id, "
            "save_version, active, soft_deleted_at) VALUES ('retention test', '{}', '', 3600, "
            "false, now(), now(), false, :uuid, :org_id, 1, :active, "
            "CASE WHEN :active THEN NULL ELSE now() END) RETURNING id",
            uuid=uuid.uuid4(),
            org_id=org_id,
            active=not in_recycle_bin,
        )

    async def session(
        self, graph_id: int | None, status="end", finished_at=EXPIRED, parent_session_id=None
    ) -> int:
        return await self.value(
            "INSERT INTO tables_session (graph_id, parent_session_id, status, status_updated_at, "
            "time_to_live, finished_at, status_data, variables, created_at, token_usage) "
            "VALUES (:graph_id, :parent_session_id, :status, :finished_at, 3600, :finished_at, "
            "'{}', '{}', :finished_at, '{}') RETURNING id",
            graph_id=graph_id,
            parent_session_id=parent_session_id,
            status=status,
            finished_at=finished_at,
        )

    async def callback(self, session_id: int, status: str) -> None:
        await self.execute(
            "INSERT INTO tables_sessioncallback (session_id, url, encrypted_secret, payload, "
            "status, attempts, last_error, created_at, updated_at) VALUES (:session_id, "
            "'http://example.test/callback', '', '{}', :status, 0, '', now(), now())",
            session_id=session_id,
            status=status,
        )

    async def storage_file(self, org_id: int) -> int:
        name = f"retention-{uuid.uuid4()}.txt"
        return await self.value(
            "INSERT INTO tables_storagefile (path, name, parent_path, item_type, is_system, org_id, "
            "created_at, updated_at, active) VALUES (:path, :name, '', 'file', false, :org_id, "
            "now(), now(), true) RETURNING id",
            path=name,
            name=name,
            org_id=org_id,
        )

    async def children(self, session_id: int, org_id: int) -> set[str]:
        """Give the session one row in every child table; return the tables filled."""
        statements = {
            "tables_graphsessionmessage": (
                "INSERT INTO tables_graphsessionmessage (session_id, created_at, name, "
                "execution_order, message_data, uuid, node_type) "
                "VALUES (:session_id, now(), 'node', 1, '{}', gen_random_uuid(), 'python')"
            ),
            "tables_usersessionmessage": (
                "INSERT INTO tables_usersessionmessage (session_id, created_at, text, "
                "execution_order, node_name) VALUES (:session_id, now(), 'hi', 1, 'node')"
            ),
            "tables_agentsessionmessage": (
                "INSERT INTO tables_agentsessionmessage (session_id, created_at, thought, text, "
                "result, execution_order, node_name) "
                "VALUES (:session_id, now(), '', '', '', 1, 'node')"
            ),
            "tables_tasksessionmessage": (
                "INSERT INTO tables_tasksessionmessage (session_id, created_at, description, name, "
                "expected_output, raw, agent, execution_order, node_name) "
                "VALUES (:session_id, now(), '', '', '', '', '', 1, 'node')"
            ),
            "tables_sessionwarningmessage": (
                "INSERT INTO tables_sessionwarningmessage (session_id, messages, created_at) "
                "VALUES (:session_id, '{}', now())"
            ),
            "tables_sessiontrigger": (
                "INSERT INTO tables_sessiontrigger (session_id, trigger_type, extra) "
                "VALUES (:session_id, 'manual', '{}')"
            ),
            "tables_sessionprincipal": (
                "INSERT INTO tables_sessionprincipal (session_id, kind) VALUES (:session_id, 'user')"
            ),
            "tables_sessioncallback": (
                "INSERT INTO tables_sessioncallback (session_id, url, encrypted_secret, payload, "
                "status, attempts, last_error, created_at, updated_at) VALUES (:session_id, "
                "'http://example.test/callback', '', '{}', 'delivered', 1, '', now(), now())"
            ),
            "tables_sessionstoragefile": (
                "INSERT INTO tables_sessionstoragefile (session_id, storage_file_id, added_at) "
                "VALUES (:session_id, :storage_file_id, now())"
            ),
            "storage_credentials_temp_account": (
                "INSERT INTO storage_credentials_temp_account (session_id, access_key, issued_at) "
                "VALUES (:session_id, :access_key, now())"
            ),
        }
        storage_file_id = await self.storage_file(org_id)
        for statement in statements.values():
            await self.execute(
                statement,
                session_id=session_id,
                storage_file_id=storage_file_id,
                access_key=f"retention-{uuid.uuid4()}",
            )
        return set(statements)

    async def remaining(self, table: str, column: str, ids: list[int]) -> int:
        return await self.value(f"SELECT count(*) FROM {table} WHERE {column} = ANY(:ids)", ids=ids)

    async def sessions_left(self, ids: list[int]) -> list[int]:
        result = await self.execute(
            "SELECT id FROM tables_session WHERE id = ANY(:ids) ORDER BY id", ids=ids
        )
        return list(result.scalars())


@pytest.fixture
def database(engine):
    return Database(engine)


async def _hold_row_lock(engine, sql: str, **params):
    """Open a transaction on its own connection that locks the rows ``sql`` selects."""
    connection = await engine.connect()
    await connection.begin()
    await connection.execute(text(sql), params)
    return connection


async def test_deletes_nested_children_with_root(repository, database):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    root = await database.session(graph_id)
    subflow = await database.session(graph_id, parent_session_id=root)
    nested_subflow = await database.session(graph_id, parent_session_id=subflow)
    tree = [root, subflow, nested_subflow]
    filled_tables = set()
    for session_id in tree:
        filled_tables |= await database.children(session_id, org_id)

    deleted = await repository.delete_expired_sessions(org_id, CUTOFF)

    assert deleted == 3
    assert await database.sessions_left(tree) == []
    # The fixture must fill every table the contract deletes, or this test proves nothing.
    assert filled_tables == {link.table for link in SESSION_CHILD_TABLES}
    for link in SESSION_CHILD_TABLES:
        assert await database.remaining(link.table, link.column, tree) == 0, link.table


async def test_skips_non_terminal_and_pending_callback(repository, database):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    kept = [
        await database.session(graph_id, status="run"),
        await database.session(graph_id, status="pending"),
        await database.session(graph_id, status="wait_for_user"),
        await database.session(graph_id, status="end", finished_at=RECENT),
    ]
    for callback_status in ("registered", "pending"):
        root = await database.session(graph_id)
        await database.callback(root, callback_status)
        kept.append(root)
    root_with_owed_subflow_callback = await database.session(graph_id)
    subflow = await database.session(graph_id, parent_session_id=root_with_owed_subflow_callback)
    await database.callback(subflow, "pending")
    kept += [root_with_owed_subflow_callback, subflow]
    deleted_roots = []
    for status, callback_status in (
        ("end", "delivered"),
        ("error", "failed"),
        ("stop", None),
        ("expired", None),
    ):
        root = await database.session(graph_id, status=status)
        if callback_status:
            await database.callback(root, callback_status)
        deleted_roots.append(root)

    deleted = await repository.delete_expired_sessions(org_id, CUTOFF)

    assert deleted == 4
    assert await database.sessions_left(kept + deleted_roots) == sorted(kept)


async def test_keeps_a_session_that_finished_exactly_at_the_cutoff(repository, database):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    at_cutoff = await database.session(graph_id, finished_at=CUTOFF)
    just_before = await database.session(graph_id, finished_at=CUTOFF - timedelta(microseconds=1))

    deleted = await repository.delete_expired_sessions(org_id, CUTOFF)

    assert deleted == 1
    assert await database.sessions_left([at_cutoff, just_before]) == [at_cutoff]


async def test_keeps_sessions_of_a_flow_in_the_recycle_bin(repository, database):
    org_id = await database.org()
    binned_root = await database.session(await database.graph(org_id, in_recycle_bin=True))
    live_root = await database.session(await database.graph(org_id))

    deleted = await repository.delete_expired_sessions(org_id, CUTOFF)

    assert deleted == 1
    assert await database.sessions_left([binned_root, live_root]) == [binned_root]


async def test_clears_set_null_links(repository, database):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    expired_root = await database.session(graph_id)
    later_run = await database.session(graph_id, finished_at=RECENT)
    trigger_id = await database.value(
        "INSERT INTO tables_sessiontrigger (session_id, trigger_type, extra, triggered_by_session_id) "
        "VALUES (:session_id, 'parent_flow', '{}', :triggered_by) RETURNING id",
        session_id=later_run,
        triggered_by=expired_root,
    )
    table_id = await database.value(
        "INSERT INTO tables_keyvaluetable (name, description, org_id, created_at, updated_at, active) "
        "VALUES ('retention', '', :org_id, now(), now(), true) RETURNING id",
        org_id=org_id,
    )
    entry_id = await database.value(
        "INSERT INTO tables_keyvaluetableentry (table_id, key, updated_by_session_id, created_at, "
        "updated_at, active) VALUES (:table_id, 'k', :session_id, now(), now(), true) RETURNING id",
        table_id=table_id,
        session_id=expired_root,
    )

    await repository.delete_expired_sessions(org_id, CUTOFF)

    assert await database.sessions_left([expired_root, later_run]) == [later_run]
    assert await database.value(
        "SELECT triggered_by_session_id FROM tables_sessiontrigger WHERE id = :id", id=trigger_id
    ) is None
    assert await database.value(
        "SELECT updated_by_session_id FROM tables_keyvaluetableentry WHERE id = :id", id=entry_id
    ) is None


async def test_keeps_storage_files(repository, database):
    org_id = await database.org()
    root = await database.session(await database.graph(org_id))
    await database.children(root, org_id)
    storage_file_id = await database.value(
        "SELECT storage_file_id FROM tables_sessionstoragefile WHERE session_id = :id", id=root
    )

    await repository.delete_expired_sessions(org_id, CUTOFF)

    assert await database.remaining("tables_sessionstoragefile", "session_id", [root]) == 0
    assert await database.remaining("tables_storagefile", "id", [storage_file_id]) == 1


async def test_only_target_org(repository, database):
    target_org = await database.org()
    other_org = await database.org()
    target_root = await database.session(await database.graph(target_org))
    other_root = await database.session(await database.graph(other_org))
    no_flow_root = await database.session(None)

    deleted = await repository.delete_expired_sessions(target_org, CUTOFF)

    assert deleted == 1
    assert await database.sessions_left([target_root, other_root, no_flow_root]) == sorted(
        [other_root, no_flow_root]
    )


async def test_sessions_without_a_flow_are_purged_without_touching_org_sessions(
    repository, database
):
    org_root = await database.session(await database.graph(await database.org()))
    no_flow_root = await database.session(None)
    recent_no_flow_root = await database.session(None, finished_at=RECENT)

    deleted = await repository.delete_expired_sessions(None, CUTOFF)

    assert deleted == 1
    assert await database.sessions_left([org_root, no_flow_root, recent_no_flow_root]) == sorted(
        [org_root, recent_no_flow_root]
    )


@pytest.mark.parametrize(("roots", "batch_size"), [(5, 2), (4, 2), (1, 2), (0, 2)])
async def test_batches_until_a_short_batch(repository, database, roots, batch_size):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    created = [await database.session(graph_id) for _ in range(roots)]

    deleted = await repository.delete_expired_sessions(org_id, CUTOFF, batch_size=batch_size)

    assert deleted == roots
    assert await database.sessions_left(created) == []


async def test_a_root_kept_by_its_subflow_callback_does_not_stall_later_batches(
    repository, database
):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    held_root = await database.session(graph_id)
    await database.callback(await database.session(graph_id, parent_session_id=held_root), "pending")
    later_roots = [await database.session(graph_id) for _ in range(3)]

    # A regression here loops forever; fail instead of hanging the suite.
    deleted = await asyncio.wait_for(
        repository.delete_expired_sessions(org_id, CUTOFF, batch_size=1), timeout=30
    )

    assert deleted == 3
    assert await database.sessions_left([held_root, *later_roots]) == [held_root]


async def test_skips_a_root_locked_by_another_transaction(engine, repository, database):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    locked_root = await database.session(graph_id)
    free_root = await database.session(graph_id)
    locker = await _hold_row_lock(
        engine, "SELECT id FROM tables_session WHERE id = :id FOR NO KEY UPDATE", id=locked_root
    )
    try:
        deleted = await asyncio.wait_for(
            repository.delete_expired_sessions(org_id, CUTOFF), timeout=30
        )
    finally:
        await locker.rollback()
        await locker.close()

    assert deleted == 1
    assert await database.sessions_left([locked_root, free_root]) == [locked_root]


async def test_holds_back_a_root_whose_subflow_is_locked_elsewhere(engine, repository, database):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    root = await database.session(graph_id)
    subflow = await database.session(graph_id, parent_session_id=root)
    locker = await _hold_row_lock(
        engine, "SELECT id FROM tables_session WHERE id = :id FOR NO KEY UPDATE", id=subflow
    )
    try:
        deleted_while_locked = await asyncio.wait_for(
            repository.delete_expired_sessions(org_id, CUTOFF), timeout=30
        )
    finally:
        await locker.rollback()
        await locker.close()
    left_while_locked = await database.sessions_left([root, subflow])

    deleted_after = await repository.delete_expired_sessions(org_id, CUTOFF)

    assert deleted_while_locked == 0
    assert left_while_locked == sorted([root, subflow])
    assert deleted_after == 2


async def test_gives_up_on_a_lock_timeout_instead_of_queueing(engine, database):
    org_id = await database.org()
    root = await database.session(await database.graph(org_id))
    await database.children(root, org_id)
    locker = await _hold_row_lock(
        engine, "SELECT id FROM tables_usersessionmessage WHERE session_id = :id FOR UPDATE", id=root
    )
    repository = RetentionRepository(
        async_sessionmaker(engine, expire_on_commit=False), lock_timeout_ms=200
    )
    started = time.monotonic()
    try:
        with pytest.raises(RetentionInterruptedError) as raised:
            await asyncio.wait_for(repository.delete_expired_sessions(org_id, CUTOFF), timeout=30)
    finally:
        await locker.rollback()
        await locker.close()

    assert time.monotonic() - started < 5
    assert raised.value.deleted == 0
    assert "lock timeout" in str(raised.value.__cause__)
    assert await database.sessions_left([root]) == [root]


async def test_failure_after_a_committed_batch_reports_the_deleted_count(engine, database):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    created = [await database.session(graph_id) for _ in range(3)]
    sessions_opened = 0
    make_session = async_sessionmaker(engine, expire_on_commit=False)

    def session_factory():
        nonlocal sessions_opened
        sessions_opened += 1
        if sessions_opened > 1:
            raise ConnectionResetError("connection reset by peer")
        return make_session()

    with pytest.raises(RetentionInterruptedError) as raised:
        await RetentionRepository(session_factory).delete_expired_sessions(
            org_id, CUTOFF, batch_size=2
        )

    assert raised.value.deleted == 2
    assert isinstance(raised.value.__cause__, ConnectionResetError)
    assert len(await database.sessions_left(created)) == 1


@pytest.fixture
def batch_log_lines():
    lines: list[str] = []
    handler_id = logger.add(
        lambda message: lines.append(message.record["message"]),
        filter=lambda record: record["message"].startswith("Retention sessions batch committed"),
    )
    yield lines
    logger.remove(handler_id)


async def test_logs_each_committed_batch(repository, database, batch_log_lines):
    org_id = await database.org()
    graph_id = await database.graph(org_id)
    root = await database.session(graph_id)
    await database.session(graph_id, parent_session_id=root)
    await database.session(graph_id)
    await database.session(graph_id)

    await repository.delete_expired_sessions(org_id, CUTOFF, batch_size=2)

    cutoff = CUTOFF.isoformat()
    assert batch_log_lines == [
        f"Retention sessions batch committed: org={org_id} cutoff={cutoff} roots_picked=2 "
        "sessions_deleted=3",
        f"Retention sessions batch committed: org={org_id} cutoff={cutoff} roots_picked=1 "
        "sessions_deleted=1",
    ]


async def test_a_purge_cancelled_after_a_batch_leaves_that_batch_logged(
    engine, database, batch_log_lines
):
    created = [await database.session(None) for _ in range(3)]
    make_session = async_sessionmaker(engine, expire_on_commit=False)
    second_batch_started = asyncio.Event()

    class NeverOpens:
        async def __aenter__(self):
            second_batch_started.set()
            await asyncio.Event().wait()

        async def __aexit__(self, *exc_info):
            return False

    sessions_opened = 0

    def session_factory():
        nonlocal sessions_opened
        sessions_opened += 1
        return make_session() if sessions_opened == 1 else NeverOpens()

    purge = asyncio.create_task(
        RetentionRepository(session_factory).delete_expired_sessions(None, CUTOFF, batch_size=2)
    )
    await asyncio.wait_for(second_batch_started.wait(), timeout=30)
    purge.cancel()
    with pytest.raises(asyncio.CancelledError):
        await purge

    assert batch_log_lines == [
        f"Retention sessions batch committed: org=no flow cutoff={CUTOFF.isoformat()} "
        "roots_picked=2 sessions_deleted=2"
    ]
    assert len(await database.sessions_left(created)) == 1


async def test_list_org_retention_reads_overrides_and_defaults(repository, database):
    without_row = await database.org()
    with_row = await database.org(sessions_days=90, with_retention_row=True)
    inherits_sessions = await database.org(sessions_days=None, with_retention_row=True)

    rows = {row.org_id: row for row in await repository.list_org_retention()}

    assert rows[without_row] == OrgRetentionRow(without_row, None, None)
    assert rows[with_row] == OrgRetentionRow(with_row, 90, 90)
    assert rows[inherits_sessions] == OrgRetentionRow(inherits_sessions, None, 90)


async def test_manager_role_has_the_grants_the_job_needs(manager_role_exists, database):
    if not manager_role_exists:
        pytest.skip(f"role {MANAGER_ROLE} does not exist on this server")
    org_id = await database.org(sessions_days=30, with_retention_row=True)
    graph_id = await database.graph(org_id)
    root = await database.session(graph_id)
    subflow = await database.session(graph_id, parent_session_id=root)
    for session_id in (root, subflow):
        await database.children(session_id, org_id)
    owed_root = await database.session(graph_id)
    await database.callback(owed_root, "pending")
    later_run = await database.session(graph_id, finished_at=RECENT)
    await database.execute(
        "INSERT INTO tables_sessiontrigger (session_id, trigger_type, extra, "
        "triggered_by_session_id) VALUES (:session_id, 'parent_flow', '{}', :root)",
        session_id=later_run,
        root=root,
    )
    table_id = await database.value(
        "INSERT INTO tables_keyvaluetable (name, description, org_id, created_at, updated_at, active) "
        "VALUES ('retention', '', :org_id, now(), now(), true) RETURNING id",
        org_id=org_id,
    )
    await database.execute(
        "INSERT INTO tables_keyvaluetableentry (table_id, key, updated_by_session_id, created_at, "
        "updated_at, active) VALUES (:table_id, 'k', :session_id, now(), now(), true)",
        table_id=table_id,
        session_id=root,
    )
    no_flow_root = await database.session(None)
    manager_engine = _engine(settings.DB_USER, settings.DB_PASSWORD)
    repository = RetentionRepository(async_sessionmaker(manager_engine, expire_on_commit=False))
    try:
        rows = await repository.list_org_retention()
        deleted = await repository.delete_expired_sessions(org_id, CUTOFF)
        deleted_without_flow = await repository.delete_expired_sessions(None, CUTOFF)
    finally:
        await manager_engine.dispose()

    assert OrgRetentionRow(org_id, 30, 90) in rows
    assert deleted == 2
    assert deleted_without_flow == 1
    assert await database.sessions_left([root, subflow, owed_root, later_run, no_flow_root]) == (
        sorted([owed_root, later_run])
    )
