import pytest

from tables.models.graph_models import Graph
from tables.models.session_models import Session
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec

GRAPH_SCHEMA = {"marker": 1}


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return GRAPH_SCHEMA


class _FakeSessionData:
    graph = _FakeGraphDump()


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(name="status-writes", org=default_org)


@pytest.fixture
def session_manager(monkeypatch):
    session_manager = SessionManagerService()
    monkeypatch.setattr(
        session_manager,
        "create_session_data",
        lambda session, **kwargs: _FakeSessionData(),
    )
    return session_manager


def _run(session_manager: SessionManagerService, graph: Graph) -> int:
    return session_manager.run_session(
        graph_id=graph.id, variables={}, trigger=TriggerSpec.manual()
    )


def _latest_session(graph: Graph) -> Session:
    return Session.objects.filter(graph=graph).latest()


@pytest.mark.django_db
def test_status_written_by_crew_during_publish_is_kept(
    graph, session_manager, monkeypatch
):
    def publish_and_finish_like_a_fast_crew(*, session_data, org_id):
        Session.objects.filter(graph=graph).update(status=Session.SessionStatus.END)
        return 2

    monkeypatch.setattr(
        session_manager.redis_service,
        "publish_session_data",
        publish_and_finish_like_a_fast_crew,
    )

    session_id = _run(session_manager, graph)

    assert Session.objects.get(pk=session_id).status == Session.SessionStatus.END


@pytest.mark.django_db
def test_failure_before_publish_marks_session_error(graph, session_manager, monkeypatch):
    def fail(*, session_data, org_id):
        raise RuntimeError("redis is down")

    monkeypatch.setattr(session_manager.redis_service, "publish_session_data", fail)

    with pytest.raises(RuntimeError):
        _run(session_manager, graph)

    session = _latest_session(graph)
    assert session.status == Session.SessionStatus.ERROR
    assert "redis is down" in session.status_data["reason"]
    assert session.finished_at is not None
    assert session.status_updated_at >= session.created_at


@pytest.mark.django_db
def test_graph_schema_is_stored(graph, session_manager, monkeypatch):
    monkeypatch.setattr(
        session_manager.redis_service,
        "publish_session_data",
        lambda *, session_data, org_id: 2,
    )

    session_id = _run(session_manager, graph)

    assert Session.objects.get(pk=session_id).graph_schema == GRAPH_SCHEMA
