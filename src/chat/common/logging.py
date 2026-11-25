import sys
import traceback

import psycopg
from loguru import logger
from psycopg.errors import ConnectionTimeout
from sqlalchemy.exc import PendingRollbackError, StatementError

__all__ = ["configure_logging", "error_summary", "traceback_without_database_text"]

# Errors whose message carries the server's text, whose DETAIL line quotes the failing row
# ("Failing row contains (...)"): SQLAlchemy's wrapper, the psycopg error it chains as its cause,
# and the error a session raises after a failed flush, which embeds the original's text and has
# no cause.
_DATABASE_ERRORS = (StatementError, PendingRollbackError, psycopg.Error)
# How psycopg words a host that does not resolve: it fails before libpq starts, so no connection
# is attached to the error.
_UNRESOLVED_HOST = "failed to resolve host "


def configure_logging(level: str) -> None:
    """Replace loguru's handlers with one stderr handler that hides variable values.

    `diagnose=False` matters: with loguru's default, exception tracebacks print the value of
    every variable on the failing lines, which writes tokens, secrets and message text into
    the logs. Calling it again replaces the handler, so it is safe per `create_app()`.
    """
    logger.remove()
    logger.add(sys.stderr, level=level, diagnose=False, backtrace=False, enqueue=False)


def error_summary(error: BaseException) -> str:
    """Return the error's type, plus what tells failures apart without quoting any data.

    For log lines that must not carry the error's text: a failed write's error quotes the
    values it wrote (message text, a desk's identity secret), an upstream error its answer's
    body. Adds a database error's SQLSTATE and constraint name, e.g.
    `IntegrityError (sqlstate 23505, constraint uq_conversation_binding_visitor_number)`.
    A failed attempt to connect to the database keeps the driver's reason instead, so an outage
    says why, e.g. `OperationalError: connection failed: ... Connection refused`. That reason
    can name the user, host and database, but never the password or any row data.
    """
    name = type(error).__name__
    connect_failure = _connect_failure(error)
    if connect_failure is not None:
        return f"{name}: {connect_failure}"
    details = _database_error_details(error)
    return f"{name} ({details})" if details else name


def traceback_without_database_text(error: BaseException) -> str:
    """Return the error's full traceback, with the text of every database error that may quote data replaced.

    Postgres's own message (primary, DETAIL, CONTEXT) quotes the row a write failed on, and
    SQLAlchemy's `hide_parameters` does not touch it; loguru's `logger.exception` always prints
    it. A database error's message therefore becomes its SQLSTATE and constraint, or only its
    type when it has neither: client-side errors included (psycopg quotes a value it fails to
    parse), and so is a connection lost during a query, whose libpq message accumulates the
    server's error for that query, DETAIL line included. Only a failed attempt to connect (one
    psycopg attaches the connection to, a connect timeout, a host that does not resolve) keeps
    the driver's reason, which can name the user, host and database but never the password or any
    row data; a SQLAlchemy wrapper of one shows only that reason, without its `[SQL: ...]` and
    parameter lines. Database errors lose their notes. The standard library formats the
    traceback, so the causes, contexts, exception groups and their limits are exactly the ones
    it shows. Every frame and every other error's text stay.
    """
    report = traceback.TracebackException.from_exception(error)
    # A stack, not recursion: a chain of causes can be longer than the interpreter's recursion limit.
    pending = [(report, error)]
    while pending:
        node, exception = pending.pop()
        if isinstance(exception, _DATABASE_ERRORS):
            # NOTE: `_str` is the private attribute holding the message in Python 3.12, which this
            # service pins (Dockerfile, pyproject.toml). tests/unit/test_unexpected_error_log.py
            # fails if an upgrade renames it and the database text comes back.
            node._str = _database_error_message(exception)
            node.__notes__ = None
        if node.__cause__ is not None:
            pending.append((node.__cause__, exception.__cause__))
        if node.__context__ is not None and not exception.__suppress_context__:
            pending.append((node.__context__, exception.__context__))
        if node.exceptions:
            # Pairing each node with its exception relies on `TracebackException` keeping every
            # group member (it limits only what `format` prints). Should an upgrade truncate them,
            # a member's text can no longer be told apart, so the whole traceback is withheld.
            if len(node.exceptions) != len(exception.exceptions):
                return f"{error_summary(error)} (traceback withheld: a group's report lost members)"
            pending.extend(zip(node.exceptions, exception.exceptions, strict=True))
    return "".join(report.format())


def _database_error_message(error: BaseException) -> str:
    connect_failure = _connect_failure(error)
    if connect_failure is not None:
        return str(connect_failure)
    return _database_error_details(error)


def _connect_failure(error: BaseException) -> psycopg.OperationalError | None:
    # Not "any connection error without a SQLSTATE": a connection lost mid-query ("consuming
    # input failed", "flushing failed") has none either, yet since libpq 14 its message carries
    # the server's error for that query, DETAIL with the failing row included.
    driver_error = error.orig if isinstance(error, StatementError) else error
    if not isinstance(driver_error, psycopg.OperationalError):
        return None
    # psycopg attaches the connection only to the errors of a connect attempt.
    if driver_error.pgconn is not None or isinstance(driver_error, ConnectionTimeout):
        return driver_error
    # psycopg's own resolver failure: no SQLSTATE, because the server never answered. An error
    # the server sent always has one, even one psycopg maps to this exact class (an unknown
    # code), so a server message worded the same way is not kept.
    if (
        type(driver_error) is psycopg.OperationalError
        and driver_error.sqlstate is None
        and str(driver_error).startswith(_UNRESOLVED_HOST)
    ):
        return driver_error
    return None


def _database_error_details(error: BaseException) -> str:
    if isinstance(error, psycopg.Error):
        server_error = error
    elif isinstance(error, StatementError):
        server_error = error.orig
    else:
        return ""
    details = []
    sqlstate = getattr(server_error, "sqlstate", None)
    if sqlstate:
        details.append(f"sqlstate {sqlstate}")
    constraint = getattr(getattr(server_error, "diag", None), "constraint_name", None)
    if constraint:
        details.append(f"constraint {constraint}")
    return ", ".join(details)
