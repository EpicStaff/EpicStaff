"""POST /api/run-session/ answers infrastructure failures as server errors, never as the 400
reserved for a fault in the flow, and never with the failure's own text."""

import re

import pytest
from django.db import connection
from django.urls import reverse
from foundation.utils.error_reference import REFERENCE_PATTERN
from psycopg_pool import PoolTimeout
from rest_framework import status

from rbac.identity.authentication import JwtOrApiKeyAuthentication
from storage_credentials.exceptions import TemporaryCredentialIssueError
from tables.models import Session
from tables.services.session_manager_service import secret_declaration_validator
from tests.fixtures import *

INTERNAL_TEXT = "relation tables_internal does not exist at 10.0.0.5"


def _pool_timeout(*args, **kwargs):
    """Fail as a query does when no pooled connection frees up in time."""
    with connection.wrap_database_errors:
        raise PoolTimeout("couldn't get a connection after 10.00 sec")


def _assert_database_busy(response):
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE, response.content
    assert response["Retry-After"] == "5"
    assert response.json() == {
        "status_code": 503,
        "code": "database_pool_exhausted",
        "message": "The server is busy. Please retry shortly.",
    }


@pytest.mark.django_db
def test_pool_timeout_during_authentication_answers_503(
    auth_client, session_data, redis_client_mock, mocker
):
    mocker.patch.object(JwtOrApiKeyAuthentication, "authenticate", side_effect=_pool_timeout)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    _assert_database_busy(response)


@pytest.mark.django_db
def test_a_server_error_raised_on_the_start_path_is_left_to_the_global_handler_and_answers_503(
    auth_client, session_data, redis_client_mock, mocker
):
    mocker.patch.object(secret_declaration_validator, "violations", side_effect=_pool_timeout)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    _assert_database_busy(response)
    redis_client_mock.publish.assert_not_called()


@pytest.mark.django_db
def test_unexpected_error_while_starting_the_session_answers_the_generic_500_citing_the_sessions_reference(
    auth_client, session_data, redis_client_mock, mocker, monkeypatch
):
    # With DEBUG on the handler leaves the exception to Django instead of rendering the 500.
    monkeypatch.setattr("utils.exception_handler.DEBUG", False)
    mocker.patch.object(
        secret_declaration_validator, "violations", side_effect=RuntimeError(INTERNAL_TEXT)
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, response.content
    body = response.json()
    assert body["code"] == "internal_error"
    assert INTERNAL_TEXT.encode() not in response.content
    assert b"RuntimeError" not in response.content
    session = Session.objects.get(graph_id=session_data["graph_id"])
    assert session.status == Session.SessionStatus.ERROR
    session_reference = re.search(
        rf"\(reference: ({REFERENCE_PATTERN})\)", session.status_data["reason"]
    ).group(1)
    assert body["reference"] == session_reference
    assert f"(reference: {session_reference})" in body["message"]


@pytest.mark.django_db
def test_server_side_domain_error_keeps_its_own_status(
    auth_client, session_data, redis_client_mock, mocker
):
    mocker.patch.object(
        secret_declaration_validator, "violations", side_effect=TemporaryCredentialIssueError()
    )

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR, response.content
    assert response.json()["code"] == "temporary_credential_issue_error"
