"""Session / ScheduleTriggerNode delete side effects fire only after the transaction commits."""

from unittest.mock import patch

import pytest
from django.db import transaction

from tables.models.graph_models import ScheduleTriggerNode
from tables.models.session_models import Session


def _stop_sent(service):
    return service.return_value.stop_session.call_args_list


def _publish_sent(service):
    return service.return_value.redis_client.publish.call_args_list


DELETES = {
    # Stopping the session in crew; tells crew a running session vanished.
    "session": (
        lambda graph: Session.objects.create(graph=graph, status=Session.SessionStatus.RUN),
        "tables.signals.session_signals.SessionManagerService",
        _stop_sent,
    ),
    # Telling the manager to drop the schedule.
    "schedule-trigger": (
        lambda graph: ScheduleTriggerNode.objects.create(graph=graph, node_name="schedule_node"),
        "tables.signals.schedule_signals.RedisService",
        _publish_sent,
    ),
}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("deleted", list(DELETES))
@pytest.mark.parametrize("commits", [True, False], ids=["committed", "rolled-back"])
def test_delete_notifies_other_services_only_once_committed(
    graph, django_capture_on_commit_callbacks, deleted, commits
):
    create, notifier, notifications = DELETES[deleted]
    instance = create(graph)

    with patch(notifier) as service, django_capture_on_commit_callbacks(execute=True):
        try:
            with transaction.atomic():
                instance.delete()
                if not commits:
                    raise RuntimeError("force a rollback")
        except RuntimeError:
            pass

    assert len(notifications(service)) == (1 if commits else 0)
