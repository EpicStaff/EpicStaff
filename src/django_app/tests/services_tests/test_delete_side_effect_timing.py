"""Verify Session/ScheduleTriggerNode delete side effects fire only after the enclosing transaction commits, not mid-transaction."""

from unittest.mock import patch

import pytest
from django.db import transaction

from tables.models.graph_models import ScheduleTriggerNode
from tables.models.session_models import Session


@pytest.mark.django_db(transaction=True)
def test_session_stop_does_not_fire_if_the_transaction_rolls_back(graph):
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)

    with patch("tables.signals.session_signals.SessionManagerService") as mock_service:
        try:
            with transaction.atomic():
                session.delete()
                raise RuntimeError("force a rollback")
        except RuntimeError:
            pass

        mock_service.return_value.stop_session.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_session_stop_fires_after_a_committed_delete(graph, django_capture_on_commit_callbacks):
    session = Session.objects.create(graph=graph, status=Session.SessionStatus.RUN)
    session_id = session.pk

    with patch("tables.signals.session_signals.SessionManagerService") as mock_service:
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                session.delete()

        mock_service.return_value.stop_session.assert_called_once_with(session_id=session_id)


@pytest.mark.django_db(transaction=True)
def test_schedule_trigger_delete_publish_does_not_fire_if_the_transaction_rolls_back(graph):
    node = ScheduleTriggerNode.objects.create(graph=graph, node_name="schedule_node")

    with patch("tables.signals.schedule_signals.RedisService") as mock_redis_service:
        try:
            with transaction.atomic():
                node.delete()
                raise RuntimeError("force a rollback")
        except RuntimeError:
            pass

        mock_redis_service.return_value.redis_client.publish.assert_not_called()


@pytest.mark.django_db(transaction=True)
def test_schedule_trigger_delete_publish_fires_after_a_committed_delete(
    graph, django_capture_on_commit_callbacks
):
    node = ScheduleTriggerNode.objects.create(graph=graph, node_name="schedule_node")

    with patch("tables.signals.schedule_signals.RedisService") as mock_redis_service:
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                node.delete()

        mock_redis_service.return_value.redis_client.publish.assert_called_once()
