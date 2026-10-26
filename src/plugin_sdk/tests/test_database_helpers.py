import asyncio
from contextlib import asynccontextmanager

import pytest

from epicstaff_plugin import database
from epicstaff_plugin.contracts import runtime
from epicstaff_plugin.database import (
    ORG_ID_SETTING,
    ConnectionInTransactionError,
    DatabaseUnavailable,
    NestedOrgTransactionError,
    connection_limit,
    database_url,
    job_transaction,
    org_transaction,
)

URL = "postgresql://weather_app:secret@plugins_db:5432/plugin_weather?application_name=weather"


# psycopg's pq.TransactionStatus values.
IDLE, IN_TRANSACTION, IN_ERROR = 0, 2, 3


class FakeConnectionInfo:
    def __init__(self, connection, user):
        self._connection = connection
        self.user = user

    @property
    def transaction_status(self):
        if self._connection.depth:
            return IN_TRANSACTION
        return self._connection.status_outside_blocks


class FakeConnection:
    """Records what the transaction helpers do with a psycopg-shaped async connection.

    `status` is its transaction status outside any `transaction()` block: IN_TRANSACTION, for
    example, for a connection that ran a query outside one.
    """

    def __init__(self, *, user="weather_app", status=IDLE):
        self.calls = []
        self.depth = 0
        self.status_outside_blocks = status
        self.info = FakeConnectionInfo(self, user)

    @asynccontextmanager
    async def transaction(self):
        self.calls.append(("begin",))
        self.depth += 1
        try:
            yield object()
        except BaseException as error:
            self.calls.append(("rollback", type(error).__name__))
            raise
        finally:
            self.depth -= 1
        self.calls.append(("commit",))

    async def execute(self, query, params):
        self.calls.append(("execute", query, params))


async def _run_in_org(connection, org_id, *, fail=False):
    async with org_transaction(connection, org_id) as yielded:
        connection.calls.append(("block", yielded is connection))
        if fail:
            raise RuntimeError("the block failed")


def test_the_environment_names_are_the_ones_the_node_sets():
    assert runtime.DATABASE_URL_ENVIRONMENT_VARIABLE == "DATABASE_URL"
    assert runtime.DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE == "EPICSTAFF_PLUGIN_DB_CONNECTIONS"
    assert ORG_ID_SETTING == "app.org_id"


def test_database_url_reads_the_variable(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", URL)

    assert database_url() == URL


@pytest.mark.parametrize("value", [None, ""], ids=["unset", "empty"])
def test_database_url_without_a_database_raises(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
    else:
        monkeypatch.setenv("DATABASE_URL", value)

    with pytest.raises(DatabaseUnavailable, match="DATABASE_URL is not set"):
        database_url()


@pytest.mark.parametrize(("value", "expected"), [("1", 1), ("3", 3), ("100", 100)])
def test_connection_limit_reads_the_variable(monkeypatch, value, expected):
    monkeypatch.setenv("EPICSTAFF_PLUGIN_DB_CONNECTIONS", value)

    assert connection_limit() == expected


@pytest.mark.parametrize("value", [None, "", "0", "-1", "3.5", "three", " 3", "٣"])
def test_connection_limit_that_is_not_a_positive_integer_raises(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("EPICSTAFF_PLUGIN_DB_CONNECTIONS", raising=False)
    else:
        monkeypatch.setenv("EPICSTAFF_PLUGIN_DB_CONNECTIONS", value)

    with pytest.raises(DatabaseUnavailable, match="EPICSTAFF_PLUGIN_DB_CONNECTIONS must be a positive integer"):
        connection_limit()


def test_org_transaction_sets_the_organization_for_the_transaction_only():
    connection = FakeConnection()

    asyncio.run(_run_in_org(connection, 3))

    assert connection.calls == [
        ("begin",),
        ("execute", "SELECT pg_catalog.set_config('app.org_id', %s, true)", ("3",)),
        ("block", True),
        ("commit",),
    ]


def test_org_transaction_rolls_back_when_the_block_raises():
    connection = FakeConnection()

    with pytest.raises(RuntimeError, match="the block failed"):
        asyncio.run(_run_in_org(connection, 7, fail=True))

    assert connection.calls[-1] == ("rollback", "RuntimeError")
    assert ("commit",) not in connection.calls


@pytest.mark.parametrize("org_id", [0, -3, True, "3", 3.0, None])
def test_org_transaction_refuses_an_id_that_is_not_a_positive_integer(org_id):
    connection = FakeConnection()

    with pytest.raises(ValueError, match="an organization id is a positive integer"):
        asyncio.run(_run_in_org(connection, org_id))

    assert connection.calls == []


SET_ORG_ID = "SELECT pg_catalog.set_config('app.org_id', %s, true)"


def test_a_nested_org_transaction_for_the_same_organization_is_a_savepoint():
    connection = FakeConnection()

    async def nested():
        async with org_transaction(connection, 3), org_transaction(connection, 3):
            connection.calls.append(("block",))

    asyncio.run(nested())

    assert connection.calls == [
        ("begin",),
        ("execute", SET_ORG_ID, ("3",)),
        ("begin",),
        ("execute", SET_ORG_ID, ("3",)),
        ("block",),
        ("commit",),
        ("commit",),
    ]


def test_a_nested_org_transaction_for_another_organization_is_refused_before_any_sql():
    connection, other_connection = FakeConnection(), FakeConnection()

    async def nested():
        async with org_transaction(connection, 3):
            with pytest.raises(NestedOrgTransactionError, match="organization 3 is open"):
                async with org_transaction(other_connection, 5):
                    pass
            await connection.execute("SELECT 1", ())

    asyncio.run(nested())

    assert other_connection.calls == []
    assert connection.calls == [
        ("begin",),
        ("execute", SET_ORG_ID, ("3",)),
        ("execute", "SELECT 1", ()),
        ("commit",),
    ]


def test_another_organization_may_follow_once_the_transaction_ended():
    connection = FakeConnection()

    async def one_after_the_other():
        with pytest.raises(RuntimeError):
            await _run_in_org(connection, 3, fail=True)
        await _run_in_org(connection, 5)

    asyncio.run(one_after_the_other())

    assert connection.calls[-3:] == [("execute", SET_ORG_ID, ("5",)), ("block", True), ("commit",)]


def test_a_task_started_inside_an_org_transaction_inherits_its_organization():
    connection = FakeConnection()

    async def child():
        async with org_transaction(FakeConnection(), 5):
            pass

    async def parent():
        async with org_transaction(connection, 3):
            with pytest.raises(NestedOrgTransactionError):
                await asyncio.create_task(child())
        # A task started outside one is free to use any organization.
        await asyncio.create_task(child())

    asyncio.run(parent())


def test_a_task_that_outlives_its_block_no_longer_holds_the_connection():
    connection = FakeConnection()

    async def child(block_ended):
        await block_ended.wait()
        # By now the pool lent the connection to another request, in organization 2's transaction.
        with pytest.raises(ConnectionInTransactionError, match="already has a transaction open"):
            async with org_transaction(connection, 1):
                pass

    async def requests():
        block_ended = asyncio.Event()
        async with org_transaction(connection, 1):
            task = asyncio.create_task(child(block_ended))
        async with org_transaction(connection, 2):
            block_ended.set()
            await task

    asyncio.run(requests())

    # No savepoint set organization 1 inside organization 2's transaction.
    assert connection.calls == [
        ("begin",),
        ("execute", SET_ORG_ID, ("1",)),
        ("commit",),
        ("begin",),
        ("execute", SET_ORG_ID, ("2",)),
        ("commit",),
    ]


def test_a_task_that_outlives_its_block_may_work_for_another_organization():
    connection, fresh = FakeConnection(), FakeConnection()

    async def child(block_ended):
        await block_ended.wait()
        async with org_transaction(fresh, 2):
            pass

    async def request():
        block_ended = asyncio.Event()
        async with org_transaction(connection, 1):
            task = asyncio.create_task(child(block_ended))
        block_ended.set()
        await task

    asyncio.run(request())

    assert fresh.calls == [("begin",), ("execute", SET_ORG_ID, ("2",)), ("commit",)]


def test_a_block_a_child_task_opened_stops_holding_the_parents_connection_when_the_parents_block_ends():
    connection, own = FakeConnection(), FakeConnection()

    async def child(child_opened, other_request_started):
        async with org_transaction(own, 1):
            child_opened.set()
            await other_request_started.wait()
            # The parent's block ended and the pool lent its connection to another request, in
            # organization 2's transaction: a savepoint there would set organization 1 in it.
            with pytest.raises(ConnectionInTransactionError, match="already has a transaction open"):
                async with org_transaction(connection, 1):
                    pass

    async def requests():
        child_opened, other_request_started = asyncio.Event(), asyncio.Event()
        async with org_transaction(connection, 1):
            task = asyncio.create_task(child(child_opened, other_request_started))
            await child_opened.wait()
        async with org_transaction(connection, 2):
            other_request_started.set()
            await task

    asyncio.run(requests())

    assert connection.calls == [
        ("begin",),
        ("execute", SET_ORG_ID, ("1",)),
        ("commit",),
        ("begin",),
        ("execute", SET_ORG_ID, ("2",)),
        ("commit",),
    ]


def test_a_block_in_a_child_task_may_use_the_parents_connection_while_the_parents_block_is_open():
    connection, own = FakeConnection(), FakeConnection()

    async def child():
        async with org_transaction(own, 1), org_transaction(connection, 1):
            pass

    async def request():
        async with org_transaction(connection, 1):
            await asyncio.create_task(child())

    asyncio.run(request())

    assert connection.calls == [
        ("begin",),
        ("execute", SET_ORG_ID, ("1",)),
        ("begin",),
        ("execute", SET_ORG_ID, ("1",)),
        ("commit",),
        ("commit",),
    ]


def test_a_task_started_in_a_nested_block_keeps_the_block_around_it_while_that_is_open():
    connection = FakeConnection()

    async def child(inner_ended):
        await inner_ended.wait()
        with pytest.raises(NestedOrgTransactionError, match="organization 3 is open"):
            async with org_transaction(FakeConnection(), 5):
                pass

    async def request():
        inner_ended = asyncio.Event()
        async with org_transaction(connection, 3):
            async with org_transaction(connection, 3):
                task = asyncio.create_task(child(inner_ended))
            inner_ended.set()
            await task

    asyncio.run(request())


# --- A connection with a transaction already open ---


@pytest.mark.parametrize("status", [IN_TRANSACTION, IN_ERROR], ids=["in_transaction", "in_error"])
def test_org_transaction_refuses_a_connection_already_in_a_transaction_before_any_sql(status):
    # A savepoint would not end the organization's setting: it would outlive the block.
    connection = FakeConnection(status=status)

    with pytest.raises(ConnectionInTransactionError, match="already has a transaction open"):
        asyncio.run(_run_in_org(connection, 3))

    assert connection.calls == []


def test_the_same_organization_on_another_busy_connection_is_refused():
    connection, busy = FakeConnection(), FakeConnection(status=IN_TRANSACTION)

    async def nested():
        async with org_transaction(connection, 3):
            with pytest.raises(ConnectionInTransactionError):
                async with org_transaction(busy, 3):
                    pass

    asyncio.run(nested())

    assert busy.calls == []


def test_the_same_organization_on_another_idle_connection_gets_a_transaction_of_its_own():
    connection, other = FakeConnection(), FakeConnection()

    async def nested():
        async with org_transaction(connection, 3), org_transaction(other, 3):
            # Nesting again on either connection is a savepoint of that connection's block.
            async with org_transaction(other, 3):
                pass

    asyncio.run(nested())

    assert other.calls == [
        ("begin",),
        ("execute", SET_ORG_ID, ("3",)),
        ("begin",),
        ("execute", SET_ORG_ID, ("3",)),
        ("commit",),
        ("commit",),
    ]


def test_a_connection_is_free_again_once_its_block_ended():
    connection = FakeConnection()

    async def one_after_the_other():
        await _run_in_org(connection, 3)
        async with job_transaction(connection):
            pass

    asyncio.run(one_after_the_other())

    assert connection.calls[-3:] == [("begin",), ("execute", SET_ROLE, ("weather_job",)), ("commit",)]


# --- job_transaction ---

SET_ROLE = "SELECT pg_catalog.set_config('role', %s, true)"


def test_job_transaction_switches_to_the_job_role_for_the_transaction_only():
    connection = FakeConnection(user="my_plugin_app")

    async def run():
        async with job_transaction(connection) as yielded:
            connection.calls.append(("block", yielded is connection))

    asyncio.run(run())

    assert connection.calls == [
        ("begin",),
        ("execute", SET_ROLE, ("my_plugin_job",)),
        ("block", True),
        ("commit",),
    ]


def test_job_transaction_rolls_back_when_the_block_raises():
    connection = FakeConnection()

    async def run():
        async with job_transaction(connection):
            raise RuntimeError("the batch failed")

    with pytest.raises(RuntimeError, match="the batch failed"):
        asyncio.run(run())

    assert connection.calls[-1] == ("rollback", "RuntimeError")


@pytest.mark.parametrize("user", ["postgres", "weather_owner", "weather_job", "_app", "weather_app_reader"])
def test_job_transaction_needs_a_connection_as_the_app_role(user):
    connection = FakeConnection(user=user)

    async def run():
        async with job_transaction(connection):
            pass

    with pytest.raises(ValueError, match="app role"):
        asyncio.run(run())

    assert connection.calls == []


@pytest.mark.parametrize("status", [IN_TRANSACTION, IN_ERROR], ids=["in_transaction", "in_error"])
def test_job_transaction_refuses_a_connection_already_in_a_transaction_before_any_sql(status):
    connection = FakeConnection(status=status)

    async def run():
        async with job_transaction(connection):
            pass

    with pytest.raises(ConnectionInTransactionError):
        asyncio.run(run())

    assert connection.calls == []


def test_a_nested_job_transaction_on_the_same_connection_is_a_savepoint():
    connection = FakeConnection()

    async def nested():
        async with job_transaction(connection), job_transaction(connection):
            pass

    asyncio.run(nested())

    assert connection.calls == [
        ("begin",),
        ("execute", SET_ROLE, ("weather_job",)),
        ("begin",),
        ("execute", SET_ROLE, ("weather_job",)),
        ("commit",),
        ("commit",),
    ]


def test_an_org_transaction_inside_a_job_transaction_is_refused_before_any_sql():
    connection, other = FakeConnection(), FakeConnection()

    async def nested():
        async with job_transaction(connection):
            with pytest.raises(NestedOrgTransactionError, match="a job_transaction is open"):
                async with org_transaction(other, 3):
                    pass

    asyncio.run(nested())

    assert other.calls == []


def test_a_job_transaction_inside_an_org_transaction_is_refused_before_any_sql():
    connection, other = FakeConnection(), FakeConnection()

    async def nested():
        async with org_transaction(connection, 3):
            with pytest.raises(NestedOrgTransactionError, match="organization 3 is open"):
                async with job_transaction(other):
                    pass

    asyncio.run(nested())

    assert other.calls == []


def test_a_task_started_inside_a_job_transaction_inherits_it():
    async def child():
        async with org_transaction(FakeConnection(), 5):
            pass

    async def parent():
        async with job_transaction(FakeConnection()):
            with pytest.raises(NestedOrgTransactionError):
                await asyncio.create_task(child())

    asyncio.run(parent())


def test_the_module_does_not_import_a_database_driver():
    # The SDK names no driver dependency; a plugin brings its own.
    assert "psycopg" not in vars(database)
