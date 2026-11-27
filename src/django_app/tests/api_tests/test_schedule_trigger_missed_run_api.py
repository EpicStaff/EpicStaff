"""The schedule-trigger node API shows a missed run in the node's timezone; a client cannot set it.

`schedule.missed_run_at` is written only when the Manager reports a missed
once-mode run; the editor displays it as wall-clock time in the node's timezone,
like the other schedule times, and an edit that leaves the schedule as it was
(a rename re-sending the unchanged schedule) keeps it.
"""

from datetime import UTC, datetime

import pytest
from django.urls import reverse
from rest_framework import status

from tables.models.graph_models import ScheduleTriggerNode

MISSED_START = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


@pytest.fixture
def missed_node(graph):
    return ScheduleTriggerNode.objects.create(
        graph=graph,
        node_name="once",
        is_active=False,
        run_mode=ScheduleTriggerNode.RunMode.ONCE,
        timezone="Europe/Kyiv",
        start_date_time=MISSED_START,
        end_type=ScheduleTriggerNode.EndType.NEVER,
        missed_run_at=MISSED_START,
    )


def _detail_url(node):
    return reverse("scheduletriggernode-detail", args=[node.id])


@pytest.mark.django_db
def test_missed_run_is_rendered_in_the_node_timezone(auth_client, missed_node):
    response = auth_client.get(_detail_url(missed_node))

    assert response.status_code == status.HTTP_200_OK, response.content
    # 09:00 UTC is 11:00 in Kyiv in November (UTC+2).
    assert response.data["schedule"]["missed_run_at"] == "2026-11-10T11:00:00"


@pytest.mark.django_db
def test_node_without_a_missed_run_renders_null(auth_client, graph):
    node = ScheduleTriggerNode.objects.create(graph=graph, node_name="fresh")

    response = auth_client.get(_detail_url(node))

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["schedule"]["missed_run_at"] is None


@pytest.mark.django_db
def test_rename_with_the_unchanged_schedule_keeps_the_missed_run_and_ignores_a_client_value(
    auth_client, missed_node
):
    response = auth_client.patch(
        _detail_url(missed_node),
        {
            "node_name": "renamed",
            "schedule": {
                "run_mode": "once",
                "timezone": "Europe/Kyiv",
                "start_date_time": "2026-11-10T11:00:00",
                "missed_run_at": None,
            },
        },
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["schedule"]["missed_run_at"] == "2026-11-10T11:00:00"
    missed_node.refresh_from_db()
    assert missed_node.node_name == "renamed"
    assert missed_node.missed_run_at == MISSED_START


@pytest.mark.django_db
def test_rescheduling_through_the_api_clears_the_missed_run(auth_client, missed_node):
    response = auth_client.patch(
        _detail_url(missed_node),
        {"schedule": {"start_date_time": "2026-11-20T11:00:00"}},
        format="json",
    )

    assert response.status_code == status.HTTP_200_OK, response.content
    assert response.data["schedule"]["missed_run_at"] is None
    missed_node.refresh_from_db()
    assert missed_node.missed_run_at is None
