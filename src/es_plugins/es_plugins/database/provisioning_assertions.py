"""What a provisioned plugin database must look like, read from `postgres` as `plugins_admin`.

Two groups, because the limits watchdog treats them differently:

- **Permissions** (`permission_problems`), which only `plugins_admin` or a superuser can change:
  - the three roles exist, and none is SUPERUSER, CREATEDB, CREATEROLE, REPLICATION or
    BYPASSRLS; the job role cannot log in, the app role can;
  - the `pg_auth_members` rows naming one of the three, as role or as member, are exactly the
    five of `expected_memberships`. That one rule says `plugins_admin` holds SET-only
    memberships, nothing inherits, and no plugin role is a member of another plugin's role;
  - the database is owned by the owner, PUBLIC cannot connect to it, and exactly the five
    roles of `CONNECT_HOLDERS` can.
- **Drift** (`drift`), which the platform restores itself: the app role's limits
  (`app_role_limits`), and the owner being able to log in.

`check` refuses either; the provisioner runs it once everything is set up.
"""

from collections import Counter
from dataclasses import dataclass

import psycopg
from src.shared.models.plugin_nodes import DesiredDatabase

from es_plugins.database.app_role_limits import drifted_limits
from es_plugins.database.connections import ADMIN_ROLE, BACKUP_ROLE, DatabaseProvisioningError

PUBLIC = "PUBLIC"
_PRIVILEGE_ATTRIBUTES = {
    "rolsuper": "SUPERUSER",
    "rolcreatedb": "CREATEDB",
    "rolcreaterole": "CREATEROLE",
    "rolreplication": "REPLICATION",
    "rolbypassrls": "BYPASSRLS",
}
_ROLES = (
    "SELECT rolname, rolcanlogin, " + ", ".join(_PRIVILEGE_ATTRIBUTES) + " "
    "FROM pg_catalog.pg_roles WHERE rolname = ANY(%s)"
)
_MEMBERSHIPS = (
    "SELECT role.rolname, member.rolname, m.admin_option, m.inherit_option, m.set_option "
    "FROM pg_catalog.pg_auth_members m "
    "JOIN pg_catalog.pg_roles role ON role.oid = m.roleid "
    "JOIN pg_catalog.pg_roles member ON member.oid = m.member "
    "WHERE role.rolname = ANY(%(roles)s) OR member.rolname = ANY(%(roles)s)"
)
_DATABASE_OWNER = (
    "SELECT pg_catalog.pg_get_userbyid(datdba) FROM pg_catalog.pg_database WHERE datname = %s"
)
# An ACL that was never set (NULL) is the default one, which lets PUBLIC connect.
_DATABASE_PRIVILEGES = (
    "SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_catalog.pg_get_userbyid(a.grantee) END, "
    "a.privilege_type FROM pg_catalog.pg_database d, "
    "pg_catalog.aclexplode(coalesce(d.datacl, pg_catalog.acldefault('d', d.datdba))) a "
    "WHERE d.datname = %s"
)


@dataclass(frozen=True, order=True)
class Membership:
    """One `pg_auth_members` row: `member` is a member of `role` with these options."""

    role: str
    member: str
    admin: bool
    inherit: bool
    set: bool

    def __str__(self) -> str:
        options = [name for name in ("admin", "inherit", "set") if getattr(self, name)]
        return f"{self.member} in {self.role} ({', '.join(options) or 'no options'})"


@dataclass(frozen=True)
class Drift:
    app_limits: list[str]
    """Names of the app role's limits that differ from the platform's (`app_role_limits`)."""

    owner_can_login: bool

    def __bool__(self) -> bool:
        return bool(self.app_limits) or self.owner_can_login


def expected_memberships(desired: DesiredDatabase) -> Counter[Membership]:
    """The memberships provisioning leaves, and the only ones there may be.

    `plugins_admin` holds ADMIN on the three roles because it created them; it holds SET (never
    INHERIT) on the owner, to create the database as it and run the owner's grants. The app role
    may SET ROLE to the job role, without inheriting its privileges.
    """
    owner, app, job = desired.owner_role, desired.app_role, desired.job_role
    return Counter(
        [
            Membership(owner, ADMIN_ROLE, admin=True, inherit=False, set=False),
            Membership(owner, ADMIN_ROLE, admin=False, inherit=False, set=True),
            Membership(app, ADMIN_ROLE, admin=True, inherit=False, set=False),
            Membership(job, ADMIN_ROLE, admin=True, inherit=False, set=False),
            Membership(job, app, admin=False, inherit=False, set=True),
        ]
    )


def connect_holders(desired: DesiredDatabase) -> set[str]:
    """The roles that may connect to the plugin's database, and the only ones."""
    return {desired.owner_role, desired.app_role, desired.job_role, ADMIN_ROLE, BACKUP_ROLE}


class ProvisioningAssertions:
    async def check(self, admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> None:
        """Refuse a database whose permissions or limits are not exactly what provisioning set.

        Raises:
            DatabaseProvisioningError: Reason `assertion`; the message lists every problem.
        """
        problems = await self.permission_problems(admin, desired)
        drift = await self.drift(admin, desired)
        if drift.app_limits:
            problems.append(
                f"the app role's {', '.join(drift.app_limits)} differ from the platform's"
            )
        if drift.owner_can_login:
            problems.append(f"role {desired.owner_role} can log in")
        if problems:
            raise DatabaseProvisioningError(
                "assertion",
                "the plugin database is not as provisioning left it: " + "; ".join(problems),
            )

    async def permission_problems(
        self, admin: psycopg.AsyncConnection, desired: DesiredDatabase
    ) -> list[str]:
        """Every way the roles, memberships and database privileges differ from provisioning's."""
        return [
            *await _role_problems(admin, desired),
            *await _membership_problems(admin, desired),
            *await _database_problems(admin, desired),
        ]

    async def drift(self, admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> Drift:
        cursor = await admin.execute(
            "SELECT rolcanlogin FROM pg_catalog.pg_roles WHERE rolname = %s",
            (desired.owner_role,),
        )
        owner = await cursor.fetchone()
        return Drift(
            app_limits=await drifted_limits(admin, desired),
            owner_can_login=owner is not None and owner[0],
        )


async def _role_problems(admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> list[str]:
    names = [desired.owner_role, desired.app_role, desired.job_role]
    cursor = await admin.execute(_ROLES, (names,))
    roles = {row[0]: row for row in await cursor.fetchall()}
    problems = []
    for name in names:
        role = roles.get(name)
        if role is None:
            problems.append(f"role {name} is missing")
            continue
        granted = [
            attribute
            for attribute, held in zip(_PRIVILEGE_ATTRIBUTES.values(), role[2:], strict=True)
            if held
        ]
        if granted:
            problems.append(f"role {name} is {' '.join(granted)}")
    if desired.job_role in roles and roles[desired.job_role][1]:
        problems.append(f"role {desired.job_role} can log in")
    if desired.app_role in roles and not roles[desired.app_role][1]:
        problems.append(f"role {desired.app_role} cannot log in")
    return problems


async def _membership_problems(
    admin: psycopg.AsyncConnection, desired: DesiredDatabase
) -> list[str]:
    roles = [desired.owner_role, desired.app_role, desired.job_role]
    cursor = await admin.execute(_MEMBERSHIPS, {"roles": roles})
    found = Counter(Membership(*row) for row in await cursor.fetchall())
    expected = expected_memberships(desired)
    problems = [f"unexpected membership {membership}" for membership in sorted(found - expected)]
    problems += [f"missing membership {membership}" for membership in sorted(expected - found)]
    return problems


async def _database_problems(admin: psycopg.AsyncConnection, desired: DesiredDatabase) -> list[str]:
    name = desired.database_name
    cursor = await admin.execute(_DATABASE_OWNER, (name,))
    owner = await cursor.fetchone()
    if owner is None:
        return [f"database {name} is missing"]
    problems = []
    if owner[0] != desired.owner_role:
        problems.append(f"database {name} is owned by {owner[0]}")
    cursor = await admin.execute(_DATABASE_PRIVILEGES, (name,))
    holders = {grantee for grantee, privilege in await cursor.fetchall() if privilege == "CONNECT"}
    if PUBLIC in holders:
        problems.append(f"PUBLIC can connect to database {name}")
    expected = connect_holders(desired)
    extra = sorted(holders - expected - {PUBLIC})
    missing = sorted(expected - holders)
    if extra:
        problems.append(f"{', '.join(extra)} can connect to database {name}")
    if missing:
        problems.append(f"{', '.join(missing)} cannot connect to database {name}")
    return problems
