import pytest
from django.urls import reverse
from rest_framework import status

from tables.models import SessionCallback
from tests.fixtures import *


@pytest.mark.django_db
def test_detail_without_callback_is_null(auth_client, session):
    response = auth_client.get(reverse("session-detail", args=[session.pk]))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["callback_status"] is None


@pytest.mark.django_db
def test_detail_shows_callback_status(auth_client, session):
    SessionCallback.objects.create(
        session=session, url="http://chat:8000/cb", secret="s" * 32, status=SessionCallback.Status.PENDING
    )

    response = auth_client.get(reverse("session-detail", args=[session.pk]))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["callback_status"] == "pending"
    assert "callback" not in response.data


@pytest.mark.django_db
def test_list_does_not_query_callback_per_row(auth_client, graph, session_factory, django_assert_max_num_queries):
    sessions = [session_factory(graph=graph) for _ in range(3)]
    for item in sessions:
        SessionCallback.objects.create(session=item, url="http://chat:8000/cb", secret="s" * 32)

    # Unfixed list is 10 queries for 3 rows (one callback query per row); fixed is 7.
    with django_assert_max_num_queries(8):
        response = auth_client.get(reverse("session-list"))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert {row["callback_status"] for row in response.data["results"]} == {"registered"}
