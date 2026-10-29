"""Purging a flow deletes its sessions in bounded batches, not all loaded at once."""

import uuid
from unittest import mock

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tables.exceptions import CrossOrgCascadeError
from tables.models import Graph
from tables.models.graph_models import GraphSessionMessage
from tables.models.session_models import Session
from tables.services.recycle_bin import purge_hooks
from tables.services.recycle_bin.purge_service import PurgeService
from tables.services.redis_service import RedisService
from tests.rbac_cross_org_fixtures import acme, beta  # noqa: F401  -- fixtures

FINISHED = Session.SessionStatus.END


def _message(session: Session) -> None:
    GraphSessionMessage.objects.create(
        session=session,
        created_at=timezone.now(),
        message_data={"message_type": "start"},
        uuid=uuid.uuid4(),
    )


def _binned_flow_with_runs(org, subflow: Graph, runs: int, status=FINISHED) -> tuple[Graph, list[int]]:
    """A binned flow with `runs` sessions, each with a sub-session of `subflow`; all with a message."""
    flow = Graph.objects.create(name=f"Flow {uuid.uuid4()}", org=org)
    session_ids = []
    for _ in range(runs):
        session = Session.objects.create(graph=flow, status=status, variables={"big": "x" * 100})
        sub_session = Session.objects.create(graph=subflow, parent_session=session, status=FINISHED)
        _message(session)
        _message(sub_session)
        session_ids += [session.pk, sub_session.pk]
    flow.delete()
    return Graph.all_objects.get(pk=flow.pk), session_ids


def _purge_query_count(flow: Graph) -> int:
    with CaptureQueriesContext(connection) as queries:
        PurgeService.purge(flow, actor="test")
    return len(queries)


@pytest.fixture
def subflow(acme):
    return Graph.objects.create(name="Subflow", org=acme)


@pytest.mark.django_db
class TestPurgingAFlowWithSessions:
    def test_deletes_every_session_sub_session_and_message_across_batches(
        self, acme, subflow, monkeypatch
    ):
        monkeypatch.setattr(purge_hooks, "SESSION_PURGE_BATCH_SIZE", 2)
        flow, session_ids = _binned_flow_with_runs(acme, subflow, runs=5)

        PurgeService.purge(flow, actor="test")

        assert not Graph.all_objects.filter(pk=flow.pk).exists()
        assert not Session.objects.filter(pk__in=session_ids).exists()
        assert not GraphSessionMessage.objects.filter(session_id__in=session_ids).exists()
        assert Graph.objects.filter(pk=subflow.pk).exists()

    def test_query_count_does_not_grow_with_the_number_of_sessions(self, acme, subflow):
        few_runs, _ = _binned_flow_with_runs(acme, subflow, runs=2)
        many_runs, _ = _binned_flow_with_runs(acme, subflow, runs=20)

        assert _purge_query_count(many_runs) == _purge_query_count(few_runs)

    def test_query_count_grows_by_the_batch_count_only(self, acme, subflow, monkeypatch):
        monkeypatch.setattr(purge_hooks, "SESSION_PURGE_BATCH_SIZE", 3)
        one_batch, _ = _binned_flow_with_runs(acme, subflow, runs=3)
        two_batches, _ = _binned_flow_with_runs(acme, subflow, runs=6)
        three_batches, _ = _binned_flow_with_runs(acme, subflow, runs=9)

        counts = [_purge_query_count(flow) for flow in (one_batch, two_batches, three_batches)]

        per_batch = counts[1] - counts[0]
        assert per_batch > 0
        assert counts[2] - counts[1] == per_batch

    def test_an_open_session_is_still_stopped(
        self, acme, subflow, django_capture_on_commit_callbacks
    ):
        flow, _ = _binned_flow_with_runs(acme, subflow, runs=1)
        open_session = Session.objects.create(graph=flow, status=Session.SessionStatus.RUN)

        with mock.patch.object(RedisService, "publish_stop_session", autospec=True) as publish:
            with django_capture_on_commit_callbacks(execute=True):
                PurgeService.purge(flow, actor="test")

        assert [call.kwargs["session_id"] for call in publish.call_args_list] == [open_session.pk]

    def test_a_session_reaching_another_org_keeps_the_flow_and_its_sessions(
        self, acme, beta, subflow
    ):
        flow, session_ids = _binned_flow_with_runs(acme, subflow, runs=2)
        beta_flow = Graph.objects.create(name="Beta flow", org=beta)
        beta_sub_session = Session.objects.create(
            graph=beta_flow, parent_session_id=session_ids[0], status=FINISHED
        )

        with pytest.raises(CrossOrgCascadeError):
            PurgeService.purge(flow, actor="test")

        assert Graph.all_objects.filter(pk=flow.pk).exists()
        assert Session.objects.filter(pk__in=[*session_ids, beta_sub_session.pk]).count() == 5
