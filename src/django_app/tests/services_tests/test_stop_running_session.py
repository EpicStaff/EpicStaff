import pytest

from tables.models.graph_models import Graph
from tables.models.session_models import Session
from tables.services.session_manager_service import SessionManagerService


@pytest.fixture
def session(default_org):
    graph = Graph.objects.create(name="stop-running-session", org=default_org)
    return Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )


def _stub_publish_stop(monkeypatch, received_count: int) -> SessionManagerService:
    session_manager = SessionManagerService()
    monkeypatch.setattr(
        session_manager.redis_service,
        "publish_stop_session",
        lambda session_id: received_count,
    )
    return session_manager


@pytest.mark.django_db
def test_stop_received_by_crew_leaves_status_to_crew(session, monkeypatch):
    session_manager = _stub_publish_stop(monkeypatch, received_count=1)

    session_manager.stop_running_session(session=session)

    session.refresh_from_db()
    assert session.status == Session.SessionStatus.RUN


@pytest.mark.django_db
def test_stop_no_crew_received_marks_session_error(session, monkeypatch):
    session_manager = _stub_publish_stop(monkeypatch, received_count=0)

    session_manager.stop_running_session(session=session)

    session.refresh_from_db()
    assert session.status == Session.SessionStatus.ERROR
    assert "crew" in session.status_data["reason"]
    assert session.finished_at is not None
