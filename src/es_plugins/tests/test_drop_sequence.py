"""Dropping a removed plugin's database and roles on a real plugins_db (marker `postgres`)."""

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from psycopg import sql

from es_plugins.database.connections import ADMIN_ROLE, DatabaseConnector
from es_plugins.database.drop_sequence import DatabaseDropError, DatabaseDropper, DroppedDatabase
from es_plugins.database.installation_lookup import installation_marker
from es_plugins.database.migration_runner import open_owner_login
from es_plugins.database.provisioner import DatabaseProvisioner
from tests.plugin_databases import (
    ConnectionSpy,
    admin_password,
    catalog_snapshot,
    connect_as,
    fetch_all,
    new_app_password,
)

pytestmark = pytest.mark.postgres


async def provision(desired, password=None):
    await DatabaseProvisioner(DatabaseConnector(admin_password())).ensure(
        "weather", desired, password or new_app_password(), []
    )


def dropper(spy=None) -> DatabaseDropper:
    return DatabaseDropper(DatabaseConnector(admin_password(), **({"connect": spy} if spy else {})))


async def as_admin(desired, *statements):
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        for statement in statements:
            await admin.execute(statement)


async def admin_rows(desired, query, parameters=None) -> list[tuple]:
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        return await fetch_all(admin, query, parameters)


async def what_is_left(desired) -> dict:
    roles = await admin_rows(
        desired,
        "SELECT rolname FROM pg_roles WHERE rolname = ANY(%s) ORDER BY 1",
        ([desired.owner_role, desired.app_role, desired.job_role],),
    )
    databases = await admin_rows(
        desired, "SELECT datname FROM pg_database WHERE datname LIKE %s ORDER BY 1", (desired.database_name + "%",)
    )
    return {"roles": roles, "databases": databases}


async def admin_memberships(desired) -> list[tuple]:
    """plugins_admin's memberships in roles that are not this plugin's, with grantor and options."""
    return await admin_rows(
        desired,
        "SELECT r.rolname, g.rolname, m.admin_option, m.inherit_option, m.set_option "
        "FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid JOIN pg_roles u ON u.oid = m.member "
        "JOIN pg_roles g ON g.oid = m.grantor WHERE u.rolname = %s AND r.rolname <> ALL(%s) ORDER BY 1, 2",
        (ADMIN_ROLE, [desired.owner_role, desired.app_role, desired.job_role]),
    )


async def test_the_database_and_roles_go_with_every_session_of_the_app_and_owner(plugin_databases):
    desired = plugin_databases()
    password = new_app_password()
    await provision(desired, password)
    other = plugin_databases()
    await provision(other)
    memberships_before = await admin_memberships(desired)
    app = await connect_as(desired.app_role, password, desired.database_name)
    job = await connect_as(desired.app_role, password, desired.database_name)
    await job.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(desired.job_role)))

    outcome = await dropper().drop(desired)

    assert outcome == DroppedDatabase(databases=1, roles=3)
    assert await what_is_left(desired) == {"roles": [], "databases": []}
    for session in (app, job):
        with pytest.raises(psycopg.OperationalError):
            await session.execute("SELECT 1")
        await session.close()
    # plugins_admin's memberships in other roles, the other plugin's included, are untouched.
    assert await admin_memberships(desired) == memberships_before
    # The other plugin's database and roles are untouched.
    assert (await what_is_left(other))["roles"] == sorted([(other.app_role,), (other.job_role,), (other.owner_role,)])
    assert (await what_is_left(other))["databases"] == [(other.database_name,)]


async def test_an_owner_session_left_open_is_ended(plugin_databases):
    desired = plugin_databases()
    await provision(desired)
    password = new_app_password()
    async with DatabaseConnector(admin_password()).admin_session(desired.server) as admin:
        await open_owner_login(admin, desired.owner_role, password, datetime.now(UTC) + timedelta(minutes=5))
    owner = await connect_as(desired.owner_role, password, desired.database_name)

    outcome = await dropper().drop(desired)

    assert outcome == DroppedDatabase(databases=1, roles=3)
    with pytest.raises(psycopg.OperationalError):
        await owner.execute("SELECT 1")
    await owner.close()


async def test_every_database_the_owner_owns_goes_and_another_roles_database_stays(plugin_databases):
    desired = plugin_databases()
    await provision(desired)
    second = desired.database_name + "_more"
    elsewhere = desired.database_name + "_admins"
    await as_admin(
        desired,
        sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(second), sql.Identifier(desired.owner_role)),
        sql.SQL("CREATE DATABASE {}").format(sql.Identifier(elsewhere)),
    )
    try:
        outcome = await dropper().drop(desired)

        assert outcome == DroppedDatabase(databases=2, roles=3)
        assert await what_is_left(desired) == {"roles": [], "databases": [(elsewhere,)]}
    finally:
        await as_admin(desired, sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(elsewhere)))


@pytest.mark.parametrize("leftover", ["a foreign marker", "no marker", "a database of that name owned by another role"])
async def test_what_another_installation_made_is_a_conflict_and_nothing_changes(plugin_databases, leftover):
    desired = plugin_databases()
    await provision(desired)
    owner = sql.Identifier(desired.owner_role)
    if leftover == "a foreign marker":
        await as_admin(
            desired,
            sql.SQL("COMMENT ON ROLE {} IS {}").format(owner, sql.Literal(installation_marker("f" * 32))),
        )
    elif leftover == "no marker":
        await as_admin(desired, sql.SQL("COMMENT ON ROLE {} IS NULL").format(owner))
    else:
        await as_admin(
            desired,
            sql.SQL("SET ROLE {}").format(owner),
            sql.SQL("DROP DATABASE {}").format(sql.Identifier(desired.database_name)),
            "RESET ROLE",
            sql.SQL("CREATE DATABASE {}").format(sql.Identifier(desired.database_name)),
        )
    before = await catalog_snapshot(desired)

    with pytest.raises(DatabaseDropError) as raised:
        await dropper().drop(desired)

    assert raised.value.reason == "conflict" and not raised.value.temporary
    assert "will not delete" in str(raised.value) and "Retry removal" in str(raised.value)
    assert await catalog_snapshot(desired) == before


async def test_nothing_there_is_done_with_nothing_dropped(plugin_databases):
    desired = plugin_databases()

    assert await dropper().drop(desired) == DroppedDatabase(databases=0, roles=0)


async def test_a_drop_that_stopped_after_the_database_finishes_with_the_roles(plugin_databases):
    desired = plugin_databases()
    await provision(desired)
    await as_admin(
        desired,
        sql.SQL("SET ROLE {}").format(sql.Identifier(desired.owner_role)),
        sql.SQL("DROP DATABASE {}").format(sql.Identifier(desired.database_name)),
        "RESET ROLE",
    )

    assert await dropper().drop(desired) == DroppedDatabase(databases=0, roles=3)
    assert await what_is_left(desired) == {"roles": [], "databases": []}


async def test_a_session_of_another_role_keeps_the_database_and_the_drop_is_tried_again(plugin_databases):
    desired = plugin_databases()
    await provision(desired)
    # Not the plugin's role: the drop never ends such a session (a backup, in practice).
    backup_like = await connect_as(ADMIN_ROLE, admin_password(), desired.database_name)
    try:
        with pytest.raises(DatabaseDropError) as raised:
            await dropper().drop(desired)
        assert raised.value.temporary and "[55006]" in str(raised.value)
        await backup_like.execute("SELECT 1")
    finally:
        await backup_like.close()

    assert await dropper().drop(desired) == DroppedDatabase(databases=1, roles=3)


async def test_every_connection_goes_to_postgres_and_the_statements_follow_the_sequence(plugin_databases):
    desired = plugin_databases()
    await provision(desired)
    spy = ConnectionSpy()

    await dropper(spy).drop(desired)

    assert {(parameters["dbname"], parameters["user"]) for parameters in spy.connections} == {("postgres", ADMIN_ROLE)}
    app, job, owner, database = desired.app_role, desired.job_role, desired.owner_role, desired.database_name

    def first(prefix: str) -> int:
        return next(index for index, statement in enumerate(spy.statements) if statement.startswith(prefix))

    order = [
        first(f'ALTER ROLE "{app}" NOLOGIN'),
        first(f'ALTER ROLE "{owner}" NOLOGIN'),
        first(f'REVOKE CONNECT ON DATABASE "{database}" FROM "{app}", "{job}"'),
        first("SELECT pid, pg_catalog.pg_terminate_backend(pid)"),
        first(f'DROP DATABASE IF EXISTS "{database}"'),
        first(f'DROP ROLE IF EXISTS "{app}", "{job}", "{owner}"'),
    ]
    assert order == sorted(order)
    assert not [statement for statement in spy.statements if "FORCE" in statement or "INHERIT TRUE" in statement]


async def test_a_self_granted_inherit_membership_left_anywhere_fails_the_check(plugin_databases):
    desired = plugin_databases()
    await provision(desired)
    other = plugin_databases()
    await provision(other)
    await as_admin(
        desired,
        sql.SQL("GRANT {} TO {} WITH INHERIT TRUE, SET FALSE").format(
            sql.Identifier(other.app_role), sql.Identifier(ADMIN_ROLE)
        ),
    )
    try:
        # PostgreSQL 17 records plugins_admin itself as the grantor of a grant it makes to itself.
        granted = await admin_rows(
            desired,
            "SELECT g.rolname, m.inherit_option FROM pg_auth_members m JOIN pg_roles r ON r.oid = m.roleid "
            "JOIN pg_roles u ON u.oid = m.member JOIN pg_roles g ON g.oid = m.grantor "
            "WHERE r.rolname = %s AND u.rolname = %s AND m.inherit_option",
            (other.app_role, ADMIN_ROLE),
        )
        assert granted == [(ADMIN_ROLE, True)]

        with pytest.raises(DatabaseDropError, match=f"inherits {other.app_role}"):
            await dropper().drop(desired)
    finally:
        await as_admin(
            desired,
            sql.SQL("REVOKE {} FROM {} GRANTED BY {}").format(
                sql.Identifier(other.app_role), sql.Identifier(ADMIN_ROLE), sql.Identifier(ADMIN_ROLE)
            ),
        )


async def test_the_init_scripts_memberships_of_plugins_admin_are_not_self_granted(plugin_databases):
    desired = plugin_databases()

    rows = await admin_rows(
        desired,
        "SELECT r.rolname, g.rolname, m.inherit_option FROM pg_auth_members m "
        "JOIN pg_roles r ON r.oid = m.roleid JOIN pg_roles u ON u.oid = m.member "
        "JOIN pg_roles g ON g.oid = m.grantor WHERE u.rolname = %s AND r.rolname LIKE 'pg\\_%%' ORDER BY 1",
        (ADMIN_ROLE,),
    )

    # INHERIT, granted by the superuser: the drop's check counts only grants of its own.
    assert rows == [("pg_signal_backend", "postgres", True), ("pg_use_reserved_connections", "postgres", True)]
