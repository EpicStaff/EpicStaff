"""An exhausted database pool renders as a retryable 503; other database errors stay the generic 500."""

import psycopg
import pytest
from django.db import connection
from psycopg_pool import PoolTimeout

from utils.exception_handler import custom_exception_handler

POOL_TIMEOUT_TEXT = "couldn't get a connection after 10.00 sec"


def _raised_through_django(driver_error: Exception) -> Exception:
    """Return `driver_error` as Django re-raises it from a query."""
    try:
        with connection.wrap_database_errors:
            raise driver_error
    except Exception as django_error:
        return django_error


@pytest.mark.parametrize(
    "exc",
    [
        pytest.param(_raised_through_django(PoolTimeout(POOL_TIMEOUT_TEXT)), id="wrapped-by-django"),
        pytest.param(PoolTimeout(POOL_TIMEOUT_TEXT), id="raw-pool-timeout"),
    ],
)
def test_pool_timeout_renders_as_503_with_retry_after(exc):
    response = custom_exception_handler(exc, {})

    assert response.status_code == 503
    assert response["Retry-After"] == "5"
    assert response.data == {
        "status_code": 503,
        "code": "database_pool_exhausted",
        "message": "The server is busy. Please retry shortly.",
    }


def test_other_operational_error_stays_the_generic_500(monkeypatch):
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)
    exc = _raised_through_django(psycopg.OperationalError("server closed the connection"))

    response = custom_exception_handler(exc, {})

    assert response.status_code == 500
    assert not response.has_header("Retry-After")
    assert b"server closed the connection" not in response.content
