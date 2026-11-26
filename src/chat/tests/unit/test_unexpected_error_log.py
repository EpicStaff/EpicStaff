import traceback

import psycopg
import pytest
from litestar import Litestar, get
from litestar.testing import TestClient
from loguru import logger
from presentation.rest.error_handlers import get_error_handlers
from psycopg.errors import FinishedPGconn
from sqlalchemy.exc import DBAPIError, PendingRollbackError

SECRET = "desk-identity-secret-0123456789"
# What Postgres answers a refused UPDATE with; psycopg puts all of it into str(error).
SERVER_TEXT = (
    'new row for relation "binding" violates check constraint "ck_binding_name"\n'
    f"DETAIL:  Failing row contains (7, Support, {SECRET})."
)
INTERNAL_ERROR = {"code": "internal_error", "message": "Internal error."}


def _refused_write() -> DBAPIError:
    try:
        raise psycopg.errors.CheckViolation(SERVER_TEXT)
    except psycopg.Error as server_error:
        try:
            # The same chain SQLAlchemy builds: its wrapper, raised from the driver's error.
            raise DBAPIError.instance(
                "UPDATE binding SET name=%(name)s", {"name": SECRET}, server_error, psycopg.Error
            ) from server_error
        except DBAPIError as wrapped:
            return wrapped


def _wrapped_by_sqlalchemy(driver_error: psycopg.Error) -> DBAPIError:
    try:
        raise driver_error
    except psycopg.Error:
        try:
            # Parameters left visible, so the test shows they are dropped by the log, not the engine.
            raise DBAPIError.instance(
                "SELECT * FROM binding WHERE name = %(name)s", {"name": SECRET}, driver_error, psycopg.Error
            ) from driver_error
        except DBAPIError as wrapped:
            return wrapped


CONNECTION_REFUSED = 'connection failed: connection to server at "127.0.0.1", port 5432 failed: Connection refused'
# What libpq reports when the server goes away before it finished answering a refused query: the
# server's error for that query is already in the message, and there is no SQLSTATE.
CONNECTION_LOST_MID_QUERY = f"consuming input failed: server closed the connection unexpectedly\n{SERVER_TEXT}"


def _raise_directly() -> None:
    raise _refused_write()


def _raise_with_a_note() -> None:
    error = _refused_write()
    error.add_note(f"while saving {SECRET}")
    raise error


def _raise_as_cause() -> None:
    raise RuntimeError("could not save the desk") from _refused_write()


def _raise_while_handling() -> None:
    try:
        raise _refused_write()
    except DBAPIError:
        raise RuntimeError("could not save the desk")


def _raise_in_group() -> None:
    raise ExceptionGroup("could not save the desk", [_refused_write()])


def _raise_in_a_mixed_group() -> None:
    raise ExceptionGroup("could not save the desks", [RuntimeError("visible detail"), _refused_write()])


def _raise_when_the_database_is_unreachable() -> None:
    # psycopg attaches the finished connection to every error of a connect attempt.
    raise _wrapped_by_sqlalchemy(psycopg.OperationalError(CONNECTION_REFUSED, pgconn=FinishedPGconn()))


def _raise_when_the_connection_is_lost_mid_query() -> None:
    raise _wrapped_by_sqlalchemy(psycopg.OperationalError(CONNECTION_LOST_MID_QUERY))


def _raise_when_a_query_is_canceled() -> None:
    # A server-classed OperationalError: the server's text, so it may quote what the query touched.
    raise _wrapped_by_sqlalchemy(psycopg.errors.QueryCanceled(f"canceling statement due to statement timeout\n{SECRET}"))


def _raise_on_a_value_the_driver_cannot_parse() -> None:
    # A client-side error the server never sent, which still quotes the value it failed on.
    raise _wrapped_by_sqlalchemy(psycopg.DataError(f"can't parse date {SECRET!r}"))


def _raise_after_a_failed_flush() -> None:
    # What a session raises on its next use after a refused flush: no cause, the original's text inside.
    raise PendingRollbackError(
        "This Session's transaction has been rolled back due to a previous exception during flush. "
        f"Original exception was: {_refused_write()}"
    )


def _raise_at_the_end_of_a_long_chain() -> None:
    # Longer than the interpreter's recursion limit, like a retry loop that chains every attempt.
    error: BaseException = _refused_write()
    for attempt in range(1200):
        try:
            raise RuntimeError(f"attempt {attempt}") from error
        except RuntimeError as wrapper:
            error = wrapper
    raise error


def _raise_in_a_wide_group() -> None:
    raise ExceptionGroup("could not save the desks", [_refused_write() for _ in range(500)])


WRAPPED = ("sqlalchemy.exc.IntegrityError: sqlstate 23514\n", "psycopg.errors.CheckViolation: sqlstate 23514\n")
# Each scenario with the lines its record shows in place of the server's text.
SCENARIOS = {
    "direct": (_raise_directly, WRAPPED),
    "note": (_raise_with_a_note, WRAPPED),
    "cause": (_raise_as_cause, WRAPPED),
    "context": (_raise_while_handling, WRAPPED),
    "group": (_raise_in_group, WRAPPED),
    "pending-rollback": (_raise_after_a_failed_flush, ("sqlalchemy.exc.PendingRollbackError\n",)),
    "long-chain": (_raise_at_the_end_of_a_long_chain, WRAPPED),
    "wide-group": (_raise_in_a_wide_group, WRAPPED),
    "mixed-group": (_raise_in_a_mixed_group, WRAPPED),
    "client-side": (_raise_on_a_value_the_driver_cannot_parse, ("sqlalchemy.exc.DataError\n", "psycopg.DataError\n")),
    "connection-lost-mid-query": (
        _raise_when_the_connection_is_lost_mid_query,
        ("sqlalchemy.exc.OperationalError\n", "psycopg.OperationalError\n"),
    ),
    "query-canceled": (
        _raise_when_a_query_is_canceled,
        ("sqlalchemy.exc.OperationalError: sqlstate 57014\n", "psycopg.errors.QueryCanceled: sqlstate 57014\n"),
    ),
}


def _raise_with_text_and_a_note() -> None:
    error = RuntimeError("visible detail 42")
    error.add_note("note for the operator")
    raise error


@get("/fail/{how:str}", sync_to_thread=False)
def fail(how: str) -> None:
    if how == "plain":
        _raise_with_text_and_a_note()
    if how == "syntax":
        compile("total = (1 +", "<desk rule>", "exec")
    if how == "unreachable":
        _raise_when_the_database_is_unreachable()
    raise_error, _ = SCENARIOS[how]
    raise_error()


@pytest.fixture
def records():
    captured: list[str] = []
    sink_id = logger.add(captured.append, level="ERROR", format="{message}")
    yield captured
    logger.remove(sink_id)


def _request(how: str) -> tuple[int, dict]:
    app = Litestar(route_handlers=[fail], exception_handlers=get_error_handlers(), debug=False)
    with TestClient(app=app) as client:
        response = client.get(f"/fail/{how}")
    return response.status_code, response.json()


@pytest.mark.parametrize("how", SCENARIOS)
def test_a_database_error_logs_its_type_sqlstate_and_frames_but_none_of_the_servers_text(records, how):
    status, body = _request(how)

    assert (status, body) == (500, INTERNAL_ERROR)
    [record] = records
    assert record.startswith(f"Unhandled error on GET /fail/{how}\n")
    _, summary_lines = SCENARIOS[how]
    for summary_line in summary_lines:
        assert summary_line in record
    assert "in _raise_" in record
    assert SECRET not in record
    assert "Failing row" not in record and "DETAIL" not in record


@pytest.mark.parametrize("how", ["cause", "context", "group"])
def test_the_error_around_a_database_error_keeps_its_text(records, how):
    _request(how)

    assert "could not save the desk" in records[0]


def test_a_mixed_group_hides_only_its_database_members_text(records):
    _request("mixed-group")

    [record] = records
    assert "RuntimeError: visible detail\n" in record
    assert SECRET not in record


def test_an_unreachable_database_logs_the_connection_failure_but_not_the_statement(records):
    status, body = _request("unreachable")

    assert (status, body) == (500, INTERNAL_ERROR)
    [record] = records
    assert f"sqlalchemy.exc.OperationalError: {CONNECTION_REFUSED}\n" in record
    assert f"psycopg.OperationalError: {CONNECTION_REFUSED}\n" in record
    assert "[SQL:" not in record
    assert SECRET not in record


def test_a_group_whose_report_does_not_match_its_members_logs_only_its_summary(records, monkeypatch):
    original_init = traceback.TracebackException.__init__

    # Should an interpreter upgrade drop group members from the report, the database error's report
    # would pair with the RuntimeError before it, whose text is kept.
    def init_dropping_the_first_group_member(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        # A nested report's members are set by its outermost constructor, after this returns.
        if getattr(self, "exceptions", None):
            self.exceptions = self.exceptions[1:]

    monkeypatch.setattr(traceback.TracebackException, "__init__", init_dropping_the_first_group_member)

    status, body = _request("mixed-group")

    assert (status, body) == (500, INTERNAL_ERROR)
    [record] = records
    assert record.startswith("Unhandled error on GET /fail/mixed-group\nExceptionGroup (traceback withheld")
    assert SECRET not in record


def test_a_wide_group_logs_a_bounded_number_of_its_members(records):
    _request("wide-group")

    [record] = records
    assert record.count("sqlalchemy.exc.IntegrityError: sqlstate 23514\n") == 15
    assert "and 485 more exceptions" in record
    assert len(record.splitlines()) < 300


def test_any_other_error_logs_its_full_traceback_text_and_notes(records):
    status, body = _request("plain")

    assert (status, body) == (500, INTERNAL_ERROR)
    [record] = records
    assert "Traceback (most recent call last):" in record and "in _raise_with_text_and_a_note" in record
    assert record.rstrip().endswith("RuntimeError: visible detail 42\nnote for the operator")


def test_a_syntax_error_keeps_its_source_line_and_caret(records):
    _request("syntax")

    [record] = records
    assert 'File "<desk rule>", line 1' in record
    assert "total = (1 +" in record and "^" in record
    assert "SyntaxError: '(' was never closed" in record
