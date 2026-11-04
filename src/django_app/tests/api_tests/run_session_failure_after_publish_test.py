"""POST /api/run-session/ answers 201 once crew has the session, whatever fails after the publish.

A 5xx at that point would make a retrying caller (the fanout tool retries one) start the
run a second time. The failures below are real database errors: inside the test's own
transaction, as inside the schedule trigger's, a failed query left unguarded would abort
the transaction the started session lives in.
"""

import json

import pytest
from django.conf import settings
from django.db import connection
from django.urls import reverse
from rest_framework import status

from tables.models import Session
from tables.models.graph_models import Edge, EndNode, StartNode
from tables.models.session_models import SessionWarningMessage
from tables.services.surface_knowledge_warning_service import SurfaceKnowledgeWarningService
from tests.fixtures import *

WARNINGS = [{"type": "surface_knowledge", "message": "A knowledge source has no search settings."}]


def _fail_with_a_database_error(*args, **kwargs):
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 / 0")


@pytest.fixture
def runnable_flow(session_data):
    graph_id = session_data["graph_id"]
    start_node = StartNode.objects.get(graph_id=graph_id)
    end_node = EndNode.objects.create(graph_id=graph_id, output_map={})
    Edge.objects.create(graph_id=graph_id, start_node_id=start_node.id, end_node_id=end_node.id)
    return session_data


def _published_session_ids(redis_client_mock) -> list[int]:
    return [
        json.loads(call.args[1])["id"]
        for call in redis_client_mock.publish.call_args_list
        if call.args[0] == settings.SESSION_SCHEMA_CHANNEL
    ]


def _assert_started_once(response, redis_client_mock):
    assert response.status_code == status.HTTP_201_CREATED, response.content
    session_id = response.data["session_id"]
    assert Session.objects.get(pk=session_id).status == Session.SessionStatus.PENDING
    assert _published_session_ids(redis_client_mock) == [session_id]


@pytest.mark.django_db
def test_failing_to_build_the_warnings_still_answers_201_with_the_running_session(
    auth_client, runnable_flow, redis_client_mock, mocker
):
    mocker.patch.object(
        SurfaceKnowledgeWarningService, "build_warnings", side_effect=_fail_with_a_database_error
    )

    response = auth_client.post(reverse("run-session"), runnable_flow, format="json")

    _assert_started_once(response, redis_client_mock)


@pytest.mark.django_db
def test_failing_to_save_the_warnings_still_answers_201_with_the_running_session(
    auth_client, runnable_flow, redis_client_mock, mocker
):
    mocker.patch.object(SurfaceKnowledgeWarningService, "build_warnings", return_value=WARNINGS)
    mocker.patch.object(
        SessionWarningMessage.objects, "create", side_effect=_fail_with_a_database_error
    )

    response = auth_client.post(reverse("run-session"), runnable_flow, format="json")

    _assert_started_once(response, redis_client_mock)
    assert not SessionWarningMessage.objects.filter(session_id=response.data["session_id"]).exists()


@pytest.mark.django_db
def test_the_warnings_of_a_started_session_are_saved(
    auth_client, runnable_flow, redis_client_mock, mocker
):
    mocker.patch.object(SurfaceKnowledgeWarningService, "build_warnings", return_value=WARNINGS)

    response = auth_client.post(reverse("run-session"), runnable_flow, format="json")

    _assert_started_once(response, redis_client_mock)
    saved = SessionWarningMessage.objects.get(session_id=response.data["session_id"])
    assert saved.messages == WARNINGS
