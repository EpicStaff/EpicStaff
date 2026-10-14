import pytest
from django.urls import reverse
from rest_framework import status

import json

from tables.models import Session
from tables.models.graph_models import Edge, EndNode, StartNode
from tests.fixtures import *


@pytest.mark.django_db
def test_run_session_stores_a_pending_session_and_hands_the_graph_to_crew(
    auth_client, redis_client_mock, session_data
):
    graph_id = session_data["graph_id"]
    start_node = StartNode.objects.get(graph_id=graph_id)
    end_node = EndNode.objects.create(graph_id=graph_id, output_map={})
    Edge.objects.create(graph_id=graph_id, start_node_id=start_node.id, end_node_id=end_node.id)

    response = auth_client.post(reverse("run-session"), session_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED, response.content
    session = Session.objects.get(pk=response.data["session_id"])
    assert (session.graph_id, session.status) == (graph_id, "pending")
    assert session.variables == session_data["variables"]
    # What crew receives: this session, its variables and the graph's node lists.
    published = [json.loads(call.args[1]) for call in redis_client_mock.publish.call_args_list]
    (session_schema,) = [message for message in published if message.get("id") == session.id]
    assert session_schema["initial_state"] == session_data["variables"]
    # The start node is not sent: the node it leads to becomes the entrypoint.
    assert session_schema["graph"]["graph_id"] == graph_id
    assert session_schema["graph"]["entrypoint"] == session_schema["graph"]["end_node"]["node_name"]


@pytest.mark.django_db
def test_get_sessions_empty(auth_client):
    url = reverse("session-list")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data == {
        "count": 0,
        "next": None,
        "previous": None,
        "results": [],
    }


@pytest.mark.django_db
def test_get_sessions_with_data(auth_client, session):
    url = reverse("session-list")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["count"] == 1
    assert len(response.data["results"]) == 1
    assert response.data["results"][0]["id"] == session.pk


@pytest.mark.django_db
def test_get_session_by_id(auth_client, session):
    url = reverse("session-detail", args=[session.pk])

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["id"] == session.pk
    assert response.data["graph"] == session.graph.id


@pytest.mark.django_db
def test_get_session_by_invalid_id(auth_client):
    url = reverse("session-detail", args=[999])

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content


@pytest.mark.django_db
def test_session_delete(auth_client, session):
    url = reverse("session-detail", args=[session.pk])

    response = auth_client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT, response.content

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND, response.content

    test_get_sessions_empty(auth_client)


@pytest.mark.django_db
def test_get_session_statuses(auth_client, session):
    url = reverse("session-statuses")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert (
        response.data.get(session.graph.id).get(Session.SessionStatus.PENDING.value)
        == 1
    )


@pytest.mark.django_db
def test_get_session_statuses_no_sessions(auth_client):
    url = reverse("session-statuses")

    response = auth_client.get(url)

    assert response.status_code == status.HTTP_200_OK, response.content
    assert len(response.data) == 0


@pytest.mark.django_db
def test_get_session_statuses_by_graph_id(auth_client, session):
    url = reverse("session-statuses")

    response = auth_client.get(url, {"graph_id": session.graph.pk})

    assert response.status_code == status.HTTP_200_OK, response.content
    assert (
        response.data.get(session.graph.id).get(Session.SessionStatus.PENDING.value)
        == 1
    )


@pytest.mark.django_db
def test_get_session_statuses_by_invalid_graph_id(auth_client, session):
    url = reverse("session-statuses")

    response = auth_client.get(url, {"graph_id": 999})

    assert response.status_code == status.HTTP_400_BAD_REQUEST, response.content
