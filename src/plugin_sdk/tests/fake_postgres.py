"""A stand-in for a psycopg connection to a local development database.

It answers exactly the statements `epicstaff_plugin.cli.development_database` sends, keeps a
ledger and the migration texts each committed transaction ran, and plays a server for the error
cases: a failing statement, and a migration that commits by itself.
"""

from types import SimpleNamespace

import psycopg

from epicstaff_plugin.cli.development_database import (
    CREATE_LEDGER,
    CURRENT_TRANSACTION,
    JOB_ROLE_QUERY,
    LOGIN_ROLE_QUERY,
    READ_LEDGER,
    RECORD_MIGRATION,
)

IDLE, IN_TRANSACTION, IN_ERROR = 0, 2, 3
# A migration holding this fails where it stands, with this message.
FAILING_STATEMENT = "RAISE EXCEPTION 'boom'"


class FakeServerError(psycopg.errors.RaiseException):
    """An error as the server sends it: SQLSTATE P0001, a message and a position."""

    def __init__(self, message, position=None):
        super().__init__(message)
        self._diagnostic = SimpleNamespace(message_primary=message, statement_position=position)

    @property
    def diag(self):
        return self._diagnostic


class _Cursor:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    def __init__(
        self,
        *,
        server_version=170011,
        login_role=("weather_app", False, False),
        job_role=(False, False, True, False),
        failure_message="boom",
    ):
        self.info = SimpleNamespace(server_version=server_version, transaction_status=IDLE)
        self.login_role = login_role
        self.job_role = job_role
        self.failure_message = failure_message
        self.ledger: dict[str, str] = {}
        self.committed_migrations: list[str] = []
        self.ledger_created = False
        self.closed = False
        self.queried_job_roles: list[str] = []
        self._pending_ledger: dict[str, str] = {}
        self._pending_migrations: list[str] = []
        self._transaction = 0

    def execute(self, query, params=None):
        if query == "BEGIN":
            self._transaction += 1
            self.info.transaction_status = IN_TRANSACTION
        elif query == "COMMIT":
            self._commit()
        elif query == "ROLLBACK":
            self._pending_ledger.clear()
            self._pending_migrations.clear()
            self.info.transaction_status = IDLE
        elif query == LOGIN_ROLE_QUERY:
            return _Cursor([self.login_role])
        elif query == JOB_ROLE_QUERY:
            self.queried_job_roles.append(params[0])
            return _Cursor([self.job_role] if self.job_role is not None else [])
        elif query == CREATE_LEDGER:
            self.ledger_created = True
        elif query == READ_LEDGER:
            return _Cursor(self.ledger.items())
        elif query == CURRENT_TRANSACTION:
            return _Cursor([(self._transaction,)])
        elif query == RECORD_MIGRATION:
            name, sha256 = params
            self._pending_ledger[name] = sha256
        else:
            self._run_migration(query)
        return _Cursor()

    def close(self):
        self.closed = True

    def _run_migration(self, text):
        if self.info.transaction_status != IN_TRANSACTION:
            raise AssertionError("a migration ran outside a transaction")
        if FAILING_STATEMENT in text:
            self.info.transaction_status = IN_ERROR
            raise FakeServerError(self.failure_message, str(text.index(FAILING_STATEMENT) + 1))
        self._pending_migrations.append(text)
        if "\nCOMMIT;" in text:
            # The file ends the node's transaction itself: what it ran so far is committed.
            self._commit()

    def _commit(self):
        self.ledger.update(self._pending_ledger)
        self.committed_migrations.extend(self._pending_migrations)
        self._pending_ledger.clear()
        self._pending_migrations.clear()
        self.info.transaction_status = IDLE
