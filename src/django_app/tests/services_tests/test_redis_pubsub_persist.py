import json

import pytest

from tables.models.graph_models import Graph, GraphOrganization, StartNode
from tables.models.session_models import Session
from tables.services import redis_pubsub


class _FakeRedis:
    def pubsub(self):
        return object()

    def keys(self, pattern):
        return []


@pytest.mark.django_db
def test_end_status_writes_back_declared_org_paths(default_org, monkeypatch):
    graph = Graph.objects.create(
        name="pubsub", org=default_org, enable_persistent_variables=True
    )
    StartNode.objects.create(
        graph=graph,
        variables={
            "variables": {"counter": 0},
            "persistent_variables": {"organization": ["counter"], "user": []},
        },
    )
    GraphOrganization.objects.create(graph=graph, persistent_variables={})
    session = Session.objects.create(
        graph=graph, status=Session.SessionStatus.RUN, variables={}
    )

    # avoid a live Redis connection in __init__
    monkeypatch.setattr(
        redis_pubsub.RedisPubSub, "_create_redis_client", lambda self: _FakeRedis()
    )
    # the handler calls close_old_connections(), which would drop the test's
    # transactional DB connection — no-op it so the handler runs to completion
    monkeypatch.setattr(redis_pubsub, "close_old_connections", lambda: None)
    svc = redis_pubsub.RedisPubSub()
    # isolate: storage-files handling is unrelated to variable write-back
    monkeypatch.setattr(svc, "_save_session_storage_files", lambda session: None)

    message = {
        "data": json.dumps(
            {
                "session_id": session.id,
                "status": Session.SessionStatus.END,
                "status_data": {"variables": {"counter": 11}},
            }
        )
    }
    svc.session_status_handler(message)

    assert GraphOrganization.objects.get(graph=graph).persistent_variables == {
        "counter": 11
    }
