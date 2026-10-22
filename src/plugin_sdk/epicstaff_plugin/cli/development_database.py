"""A local database for `epicstaff-plugin dev`: its roles, and the plugin's migrations on it.

On EpicStaff the plugin node gives a plugin's database three roles: an owner the migrations run
as, the app role the backend logs in as, and a job role the app role may switch to
(`epicstaff_plugin.database.job_transaction`). A development backend uses a local database with
two:

- a login role named `<name>_app`, which owns the database and plays both owner and app;
- a NOLOGIN role `<name>_job`, granted to the login role `WITH INHERIT FALSE, SET TRUE`, as the
  node grants it: the app role may switch to it, and never gets its policies or privileges
  otherwise.

Neither may be a superuser or bypass row-level security. What differs from EpicStaff is that the
login role also owns the tables: the backend could change them while it runs, and a table's
policies do not apply to it unless the table has FORCE ROW LEVEL SECURITY, since PostgreSQL
exempts a table's owner otherwise. On EpicStaff the app role owns no table, so they always apply
to it. They apply to the job role here as there. `dev` names the tables this concerns
(`tables_exempt_from_their_policies`).

The migrations are applied as the node applies them (`epicstaff_plugin.contracts.database`): in
name order, each file whole and in one transaction together with its ledger row, with
`${owner_role}` and `${app_role}` replaced by the login role and `${job_role}` by the job role.
A file already in the ledger with the same SHA-256 is skipped; with another the run stops. A
failing file rolls back alone and stops the run, and so does a file that ends its own transaction.

psycopg 3 is the plugin's dependency, not the SDK's, so it is imported only once a database is
given. The connection runs in autocommit, so each transaction here is opened explicitly.
"""

import contextlib
import hashlib
import re
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from types import ModuleType
from typing import Any, Protocol
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

from epicstaff_plugin.contracts.database import (
    MIGRATION_PLACEHOLDERS,
    MIGRATIONS_LEDGER_SCHEMA,
    MIGRATIONS_LEDGER_TABLE,
)
from epicstaff_plugin.database import APP_ROLE_SUFFIX, JOB_ROLE_SUFFIX
from epicstaff_plugin.package_layout import (
    DATABASE_DIRECTORY,
    MIGRATION_PATTERN,
    migration_problems,
)
from epicstaff_plugin.package_source import PackageSource

MINIMUM_SERVER_VERSION = 160000
"""PostgreSQL 16, the first with `GRANT ... WITH INHERIT FALSE, SET TRUE`."""
DATABASE_URL_SCHEMES = ("postgresql", "postgres")
CONNECT_TIMEOUT_SECONDS = 10
MASK = "***"
# psycopg's `pq.TransactionStatus.INTRANS`: a transaction is open and has not failed.
_IN_TRANSACTION = 2
_MAX_ERROR_TEXT = 500
_BYTE_ORDER_MARK = "﻿"
_UNQUOTED_IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*")
_PASSWORD_PARAMETER = "password"


def quote_identifier(name: str) -> str:
    """`name` as a quoted SQL identifier, as PostgreSQL and psycopg's `sql.Identifier` quote it."""
    return '"' + name.replace('"', '""') + '"'


LEDGER = f"{quote_identifier(MIGRATIONS_LEDGER_SCHEMA)}.{quote_identifier(MIGRATIONS_LEDGER_TABLE)}"
CREATE_LEDGER = (
    f"CREATE SCHEMA IF NOT EXISTS {quote_identifier(MIGRATIONS_LEDGER_SCHEMA)}; "
    f"CREATE TABLE IF NOT EXISTS {LEDGER} ("
    "name text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"
)
READ_LEDGER = f"SELECT name, sha256 FROM {LEDGER}"
RECORD_MIGRATION = f"INSERT INTO {LEDGER} (name, sha256) VALUES (%s, %s)"
CURRENT_TRANSACTION = "SELECT pg_catalog.pg_current_xact_id()::text::bigint"
LOGIN_ROLE_QUERY = (
    "SELECT rolname, rolsuper, rolbypassrls FROM pg_catalog.pg_roles WHERE rolname = current_user"
)
# Tables with row-level security whose policies the session's role is exempt from: it owns them
# (or is a member of their owner), and they are not forced.
EXEMPT_TABLES_QUERY = (
    "SELECT n.nspname, c.relname FROM pg_catalog.pg_class c "
    "JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace "
    "WHERE c.relkind IN ('r', 'p') AND c.relrowsecurity AND NOT c.relforcerowsecurity "
    "AND pg_catalog.pg_has_role(current_user, c.relowner, 'USAGE') ORDER BY 1, 2"
)
JOB_ROLE_QUERY = (
    "SELECT rolsuper, rolbypassrls, pg_catalog.pg_has_role(current_user, oid, 'SET'), "
    "pg_catalog.pg_has_role(current_user, oid, 'USAGE') FROM pg_catalog.pg_roles WHERE rolname = %s"
)


class DevelopmentDatabaseError(Exception):
    """The local database cannot serve a development backend; the message says why and what to do."""


class DatabaseCursor(Protocol):
    def fetchone(self) -> tuple[Any, ...] | None: ...

    def fetchall(self) -> list[tuple[Any, ...]]: ...


class DevelopmentConnection(Protocol):
    """What this module needs of a connection; a psycopg 3 `Connection` in autocommit has it.

    `info` has `server_version` (`170011` for 17.11) and `transaction_status`.
    """

    @property
    def info(self) -> Any: ...

    def execute(self, query: str, params: Sequence[Any] | None = None) -> DatabaseCursor: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class DatabaseUrl:
    """A `postgresql://` URL, and how it may be shown: with its password masked."""

    value: str = field(repr=False)
    shown: str
    hidden: tuple[str, ...] = field(repr=False)
    """The password as the URL spells it and as it reads decoded, longest first."""

    @classmethod
    def parse(cls, value: str) -> "DatabaseUrl":
        """Read a database URL.

        Raises:
            ValueError: `value` is not a `postgresql://` URL. The message never repeats it.
        """
        try:
            parts = urlsplit(value)
            # urlsplit checks the port only when it is read.
            _ = parts.port
        except ValueError:
            raise ValueError("--database-url is not a valid postgresql:// URL") from None
        if parts.scheme not in DATABASE_URL_SCHEMES:
            raise ValueError("--database-url must be a postgresql:// URL")
        spelled = [_userinfo_password(parts), *_query_passwords(parts.query)]
        hidden = {
            text for password in spelled if password for text in (password, unquote(password))
        }
        return cls(
            value=value,
            shown=_masked(parts),
            hidden=tuple(sorted(hidden, key=len, reverse=True)),
        )

    def scrub(self, text: str) -> str:
        """`text` without this URL's password, for a driver message that may echo the URL."""
        for secret in self.hidden:
            text = text.replace(secret, MASK)
        return text


def _userinfo_password(parts: SplitResult) -> str | None:
    userinfo, separator, _ = parts.netloc.rpartition("@")
    if not separator or ":" not in userinfo:
        return None
    return userinfo.partition(":")[2]


def _is_password_parameter(pair: str) -> bool:
    # libpq decodes a parameter's name too: `pass%77ord=` is a password.
    name, separator, _ = pair.partition("=")
    return bool(separator) and unquote(name) == _PASSWORD_PARAMETER


def _query_passwords(query: str) -> list[str]:
    """The values of the query's `password` parameters, as the URL spells them."""
    return [pair.partition("=")[2] for pair in query.split("&") if _is_password_parameter(pair)]


def _masked(parts: SplitResult) -> str:
    userinfo, separator, host = parts.netloc.rpartition("@")
    netloc = parts.netloc
    if separator and ":" in userinfo:
        netloc = f"{userinfo.partition(':')[0]}:{MASK}@{host}"
    query = "&".join(
        f"{pair.partition('=')[0]}={MASK}" if _is_password_parameter(pair) else pair
        for pair in parts.query.split("&")
    )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))


@dataclass(frozen=True)
class DatabaseRoles:
    """The two roles of a development database."""

    login_role: str
    """`<name>_app`: owner and app."""

    job_role: str
    """`<name>_job`: what `job_transaction` switches to."""

    def placeholder_replacements(self) -> dict[str, str]:
        """Each `${<placeholder>}` of a migration, and the quoted role it becomes."""
        roles = {
            "owner_role": self.login_role,
            "app_role": self.login_role,
            "job_role": self.job_role,
        }
        return {"${" + name + "}": quote_identifier(roles[name]) for name in MIGRATION_PLACEHOLDERS}


@dataclass(frozen=True)
class Migration:
    """One migration file of the source."""

    name: str
    sha256: str
    """Of the file's bytes, as the package would list it."""

    content: bytes = field(repr=False)


@dataclass(frozen=True)
class MigrationRun:
    applied: tuple[str, ...]
    """The files this run applied, in order."""

    already_applied: int


def connect(url: DatabaseUrl) -> DevelopmentConnection:
    """Open an autocommit session on the local database.

    Raises:
        DevelopmentDatabaseError: psycopg is not installed, or the session cannot be opened. The
            message never holds the password.
    """
    psycopg = _psycopg()
    try:
        return psycopg.connect(url.value, autocommit=True, connect_timeout=CONNECT_TIMEOUT_SECONDS)
    except psycopg.Error as error:
        raise DevelopmentDatabaseError(
            f"cannot connect to {url.shown}: {describe_error(error, scrub=url.scrub)}"
        ) from None


def check_roles(connection: DevelopmentConnection, plugin_identifier: str) -> DatabaseRoles:
    """Check that the session's roles make row-level security apply as on EpicStaff.

    Raises:
        DevelopmentDatabaseError: The server is older than PostgreSQL 16, or a role is wrong;
            the message then shows the SQL that creates suitable roles and a database.
    """
    version = connection.info.server_version
    if version < MINIMUM_SERVER_VERSION:
        raise DevelopmentDatabaseError(
            f"the database runs PostgreSQL {version // 10000}; a development database needs "
            f"PostgreSQL {MINIMUM_SERVER_VERSION // 10000} or later"
        )
    login_role, superuser, bypasses_rls = connection.execute(LOGIN_ROLE_QUERY).fetchone()
    name = _role_name_prefix(login_role, plugin_identifier)
    if superuser or bypasses_rls:
        raise _role_error(
            f"{login_role} is a superuser or bypasses row-level security, so row-level security "
            "would not apply as on EpicStaff",
            name,
        )
    if not login_role.endswith(APP_ROLE_SUFFIX) or login_role == APP_ROLE_SUFFIX:
        raise _role_error(
            f"log in as a role named <name>{APP_ROLE_SUFFIX}, not {login_role}: the backend's "
            f"job transactions switch to <name>{JOB_ROLE_SUFFIX}",
            name,
        )
    job_role = login_role.removesuffix(APP_ROLE_SUFFIX) + JOB_ROLE_SUFFIX
    row = connection.execute(JOB_ROLE_QUERY, (job_role,)).fetchone()
    if row is None:
        raise _role_error(f"the job role {job_role} does not exist", name)
    job_superuser, job_bypasses_rls, can_switch, inherits = row
    if job_superuser or job_bypasses_rls:
        raise _role_error(
            f"{job_role} is a superuser or bypasses row-level security, so row-level security "
            "would not apply as on EpicStaff",
            name,
        )
    if not can_switch:
        raise _role_error(f"{login_role} may not switch to {job_role}", name)
    if inherits:
        raise _role_error(
            f"{login_role} inherits {job_role}, so the job role's policies would apply to every "
            "request",
            name,
        )
    return DatabaseRoles(login_role=login_role, job_role=job_role)


def tables_exempt_from_their_policies(connection: DevelopmentConnection) -> tuple[str, ...]:
    """The tables with row-level security whose policies do not apply to the login role here.

    It owns them, and they lack FORCE ROW LEVEL SECURITY; on EpicStaff the app role owns none,
    so their policies apply to it there. Each is `schema.table`, quoted where SQL needs it and
    with control characters shown as `?`.

    Raises:
        DevelopmentDatabaseError: The catalog could not be read.
    """
    psycopg = _psycopg()
    try:
        rows = connection.execute(EXEMPT_TABLES_QUERY).fetchall()
    except psycopg.Error as error:
        raise DevelopmentDatabaseError(
            f"cannot read which tables have row-level security: {describe_error(error)}"
        ) from None
    return tuple(f"{_shown_name(schema)}.{_shown_name(table)}" for schema, table in rows)


def _shown_name(name: str) -> str:
    printable = "".join(
        "?" if unicodedata.category(character) in ("Cc", "Cs") else character for character in name
    )
    return _shown_identifier(printable)


def role_setup_sql(name: str) -> str:
    """The SQL, run as a superuser, that creates `<name>_app`, `<name>_job` and a database."""
    app_role = _shown_identifier(name + APP_ROLE_SUFFIX)
    job_role = _shown_identifier(name + JOB_ROLE_SUFFIX)
    database = _shown_identifier(f"{name}_development")
    return "\n".join(
        [
            f"CREATE ROLE {job_role} NOLOGIN;",
            f"CREATE ROLE {app_role} LOGIN PASSWORD '<password>';",
            f"GRANT {job_role} TO {app_role} WITH INHERIT FALSE, SET TRUE;",
            f"CREATE DATABASE {database} OWNER {app_role};",
        ]
    )


def _role_error(problem: str, name: str) -> DevelopmentDatabaseError:
    return DevelopmentDatabaseError(
        f"{problem}.\nCreate the roles and a database as a superuser of your PostgreSQL, then pass "
        f"a URL that logs in as {name}{APP_ROLE_SUFFIX}:\n\n{role_setup_sql(name)}"
    )


def _role_name_prefix(login_role: str, plugin_identifier: str) -> str:
    if login_role.endswith(APP_ROLE_SUFFIX) and login_role != APP_ROLE_SUFFIX:
        return login_role.removesuffix(APP_ROLE_SUFFIX)
    return plugin_identifier.replace("-", "_")


def _shown_identifier(name: str) -> str:
    return name if _UNQUOTED_IDENTIFIER.fullmatch(name) else quote_identifier(name)


def source_migrations(source: PackageSource) -> list[Migration]:
    """Read the source's migrations in name order, refusing any the plugin node would refuse.

    Raises:
        DevelopmentDatabaseError: A `database/` file is not a migration named
            `database/migrations/NNN_<name>.sql`, two share a number, or together they are
            larger than the package allows.
    """
    files = {
        file.path: file.source for file in source.files if file.path.startswith(DATABASE_DIRECTORY)
    }
    if problems := migration_problems({path: file.stat().st_size for path, file in files.items()}):
        raise DevelopmentDatabaseError(
            "\n".join(f"{problem.loc}: {problem.message}" for problem in problems)
        )
    migrations = []
    for path in sorted(files):
        content = files[path].read_bytes()
        name = MIGRATION_PATTERN.match(path).group(1)
        migrations.append(
            Migration(name=name, sha256=hashlib.sha256(content).hexdigest(), content=content)
        )
    return migrations


def apply_migrations(
    connection: DevelopmentConnection, roles: DatabaseRoles, migrations: Sequence[Migration]
) -> MigrationRun:
    """Apply the migrations the ledger does not list yet; see the module docstring.

    Raises:
        DevelopmentDatabaseError: The ledger cannot be created or read, a migration changed after
            it was applied, or one failed (`<name> line <n>: [<SQLSTATE>] <message>`). The files
            applied before it stay applied.
    """
    psycopg = _psycopg()
    try:
        connection.execute("BEGIN")
        connection.execute(CREATE_LEDGER)
        connection.execute("COMMIT")
        recorded = dict(connection.execute(READ_LEDGER).fetchall())
    except psycopg.Error as error:
        _roll_back(connection, psycopg)
        raise DevelopmentDatabaseError(
            f"cannot create or read the ledger {MIGRATIONS_LEDGER_SCHEMA}.{MIGRATIONS_LEDGER_TABLE}: "
            f"{describe_error(error)}"
        ) from None
    replacements = roles.placeholder_replacements()
    applied = []
    already_applied = 0
    for migration in sorted(migrations, key=lambda migration: migration.name):
        if migration.name in recorded:
            if recorded[migration.name] != migration.sha256:
                raise DevelopmentDatabaseError(
                    f"{migration.name} changed after it was applied; add a new migration instead, "
                    "or start again with an empty database"
                )
            already_applied += 1
            continue
        _apply_one(connection, migration, _migration_text(migration, replacements), psycopg)
        applied.append(migration.name)
    return MigrationRun(applied=tuple(applied), already_applied=already_applied)


def _apply_one(
    connection: DevelopmentConnection, migration: Migration, text: str, psycopg: ModuleType
) -> None:
    try:
        connection.execute("BEGIN")
        transaction = _current_transaction(connection)
        # No parameters: psycopg sends the text as one simple query, every statement in it.
        connection.execute(text)
        # A file that ended the transaction itself is caught before its ledger row: either none
        # is open any more, or a BEGIN after its COMMIT opened another one.
        if (
            connection.info.transaction_status != _IN_TRANSACTION
            or _current_transaction(connection) != transaction
        ):
            _roll_back(connection, psycopg)
            raise DevelopmentDatabaseError(
                f"{migration.name} ends its own transaction (COMMIT or ROLLBACK); a migration runs "
                "in the one transaction it is given"
            )
        connection.execute(RECORD_MIGRATION, (migration.name, migration.sha256))
        connection.execute("COMMIT")
    except psycopg.Error as error:
        _roll_back(connection, psycopg)
        raise DevelopmentDatabaseError(
            f"{migration.name}{_line_of(text, error)}: {describe_error(error)}"
        ) from None


def _current_transaction(connection: DevelopmentConnection) -> int:
    return connection.execute(CURRENT_TRANSACTION).fetchone()[0]


def _roll_back(connection: DevelopmentConnection, psycopg: ModuleType) -> None:
    with contextlib.suppress(psycopg.Error):
        connection.execute("ROLLBACK")


def _migration_text(migration: Migration, replacements: dict[str, str]) -> str:
    try:
        text = migration.content.decode("utf-8")
    except UnicodeDecodeError:
        raise DevelopmentDatabaseError(f"{migration.name} is not UTF-8 text") from None
    text = text.removeprefix(_BYTE_ORDER_MARK)
    for placeholder, quoted in replacements.items():
        text = text.replace(placeholder, quoted)
    return text


def _line_of(text: str, error: Exception) -> str:
    """` line <n>` where the server placed the error; empty when it named no position."""
    position = error.diag.statement_position
    if not position:
        return ""
    # Counted in characters from 1. A placeholder never spans lines, so the line of the
    # replaced text is the line of the file.
    line = text[: int(position) - 1].count("\n") + 1
    return f" line {line}"


def describe_error(error: Exception, *, scrub: Callable[[str], str] | None = None) -> str:
    """`[SQLSTATE] message` of an error the server sent, or psycopg's own message, on one line.

    Control characters become spaces and runs of spaces one, so a message a migration chose can
    never start a line of its own. `scrub` takes secrets out of the text first: cleaning or
    cutting it could split one so that it no longer matches.
    """
    if error.sqlstate:
        text = f"[{error.sqlstate}] {error.diag.message_primary or ''}"
    else:
        text = str(error)
    if scrub is not None:
        text = scrub(text)
    spaced = "".join(
        " " if unicodedata.category(character) in ("Cc", "Cs") else character for character in text
    )
    return " ".join(spaced.split())[:_MAX_ERROR_TEXT]


def _psycopg() -> ModuleType:
    try:
        import psycopg
    except ImportError:
        raise DevelopmentDatabaseError(
            "psycopg is not installed in this environment: install the backend's lock here "
            "(a plugin with a database pins psycopg[binary,pool])"
        ) from None
    return psycopg
