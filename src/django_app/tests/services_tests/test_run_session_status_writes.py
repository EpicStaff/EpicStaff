import pytest

from src.shared.models import GraphData, SessionData
from tables.models.graph_models import Graph
from tables.models.session_models import Session
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec
from utils.logger import logger

GRAPH_NAME = "status-writes-schema"


@pytest.fixture
def graph(default_org):
    return Graph.objects.create(name="status-writes", org=default_org)


@pytest.fixture
def session_manager(monkeypatch):
    session_manager = SessionManagerService()

    # A real, empty SessionData: the test graph has no nodes to build one from, and
    # code that walks the payload (storage demand, publishing) keeps up with new fields.
    def empty_session_data(session, **kwargs):
        graph = GraphData(name=GRAPH_NAME, entrypoint="__end__", end_node=None)
        return SessionData(id=session.id, org_id=session.graph.org_id, audit_retention_days=0, graph=graph)

    monkeypatch.setattr(session_manager, "create_session_data", empty_session_data)
    return session_manager


def _run(session_manager: SessionManagerService, graph: Graph) -> int:
    return session_manager.run_session(
        graph_id=graph.id, variables={}, trigger=TriggerSpec.manual()
    )


def _latest_session(graph: Graph) -> Session:
    return Session.objects.filter(graph=graph).latest()


def _stub_publish(monkeypatch, session_manager: SessionManagerService, received_count: int):
    monkeypatch.setattr(
        session_manager.redis_service,
        "publish_session_data",
        lambda *, session_data, org_id, storage_credentials=None: received_count,
    )


@pytest.mark.django_db
def test_run_session_logs_variable_keys_not_values(
    graph, session_manager, monkeypatch
):
    _stub_publish(monkeypatch, session_manager, received_count=1)
    messages: list[str] = []
    sink_id = logger.add(messages.append, level="TRACE", format="{message}")
    try:
        session_manager.run_session(
            graph_id=graph.id,
            variables={"files": {"report": {"base64_data": "VALUE_MUST_NOT_BE_LOGGED"}}},
            trigger=TriggerSpec.manual(),
        )
    finally:
        logger.remove(sink_id)

    log_text = "".join(messages)
    assert "'run_session' got variables with keys: ['files']" in log_text
    assert "VALUE_MUST_NOT_BE_LOGGED" not in log_text


@pytest.mark.django_db
def test_status_written_by_crew_during_publish_is_kept(
    graph, session_manager, monkeypatch
):
    def publish_and_finish_like_a_fast_crew(*, session_data, org_id, storage_credentials=None):
        Session.objects.filter(graph=graph).update(status=Session.SessionStatus.END)
        return 1

    monkeypatch.setattr(
        session_manager.redis_service,
        "publish_session_data",
        publish_and_finish_like_a_fast_crew,
    )

    session_id = _run(session_manager, graph)

    assert Session.objects.get(pk=session_id).status == Session.SessionStatus.END


@pytest.mark.django_db
def test_failure_before_publish_marks_session_error(graph, session_manager, monkeypatch):
    def fail(*, session_data, org_id, storage_credentials=None):
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
def test_session_no_crew_received_is_marked_error(graph, session_manager, monkeypatch):
    _stub_publish(monkeypatch, session_manager, received_count=0)

    session_id = _run(session_manager, graph)

    session = Session.objects.get(pk=session_id)
    assert session.status == Session.SessionStatus.ERROR
    assert "crew" in session.status_data["reason"]
    assert session.finished_at is not None


@pytest.mark.parametrize("received_count", [1, 3])
@pytest.mark.django_db
def test_session_received_by_any_subscriber_stays_pending(
    graph, session_manager, monkeypatch, received_count
):
    _stub_publish(monkeypatch, session_manager, received_count=received_count)

    session_id = _run(session_manager, graph)

    assert Session.objects.get(pk=session_id).status == Session.SessionStatus.PENDING
