import psycopg
import pytest
from common.logging import configure_logging, error_summary
from loguru import logger
from psycopg.errors import ConnectionTimeout, FinishedPGconn, QueryCanceled
from sqlalchemy.exc import DBAPIError


def test_tracebacks_do_not_print_local_variable_values(capsys):
    configure_logging("INFO")

    def fail():
        secret_value = "s3cr3t-token-value"
        raise RuntimeError(len(secret_value))

    try:
        fail()
    except RuntimeError:
        logger.exception("boom")

    stderr = capsys.readouterr().err
    assert "boom" in stderr
    assert "s3cr3t-token-value" not in stderr


SECRET = "desk-identity-secret-0123456789"


def test_a_database_error_without_a_server_state_and_any_other_error_are_summarized_by_type_alone():
    # SQLAlchemy wraps a client-side refusal the server never saw, so there is no SQLSTATE.
    refused = DBAPIError("INSERT INTO message VALUES (%(content)s)", {"content": SECRET}, Exception(SECRET))
    assert (error_summary(refused), error_summary(ValueError(SECRET))) == ("DBAPIError", "ValueError")


AUTH_FAILED = (
    'connection failed: connection to server at "10.0.0.5", port 5432 failed: '
    'FATAL:  password authentication failed for user "chat"'
)
UNRESOLVED = "failed to resolve host 'chatdb': [Errno -2] Name or service not known"
SERVER_TEXT = f'new row for relation "binding" violates check constraint "ck_binding_name"\nDETAIL:  Failing row contains (7, {SECRET}).'


def _unmapped_server_error(message: str) -> psycopg.OperationalError:
    """The exact base class psycopg raises for a server code it has no class for."""
    error = psycopg.OperationalError(message)
    error.sqlstate = "38ZZZ"
    return error


def _wrapped(driver_error: psycopg.Error) -> DBAPIError:
    return DBAPIError.instance("SELECT %(name)s", {"name": SECRET}, driver_error, psycopg.Error)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        # A connect attempt: psycopg attaches the finished connection, and libpq's reason stays.
        (psycopg.OperationalError(AUTH_FAILED, pgconn=FinishedPGconn()), f"OperationalError: {AUTH_FAILED}"),
        (_wrapped(psycopg.OperationalError(AUTH_FAILED, pgconn=FinishedPGconn())), f"OperationalError: {AUTH_FAILED}"),
        (ConnectionTimeout("connection timeout expired"), "ConnectionTimeout: connection timeout expired"),
        (psycopg.OperationalError(UNRESOLVED), f"OperationalError: {UNRESOLVED}"),
        # A connection lost mid-query: libpq's message already holds the server's error for that query.
        (psycopg.OperationalError(f"consuming input failed: server closed the connection\n{SERVER_TEXT}"), "OperationalError"),
        (_wrapped(psycopg.OperationalError(f"flushing failed: {SERVER_TEXT}")), "OperationalError"),
        # Server-classed: the server's text, even when it reads like a connect failure.
        (QueryCanceled(f"canceling statement due to statement timeout\n{SECRET}"), "QueryCanceled (sqlstate 57014)"),
        (QueryCanceled(f"{UNRESOLVED} {SECRET}"), "QueryCanceled (sqlstate 57014)"),
        (_unmapped_server_error(f"{UNRESOLVED} {SECRET}"), "OperationalError (sqlstate 38ZZZ)"),
        # Never raised by a connect attempt to the server; its text can quote data.
        (psycopg.InterfaceError(f"unexpected result from command {SECRET!r}"), "InterfaceError"),
    ],
)
def test_only_a_failed_connect_attempt_keeps_its_reason_in_the_summary(error, expected):
    assert error_summary(error) == expected
