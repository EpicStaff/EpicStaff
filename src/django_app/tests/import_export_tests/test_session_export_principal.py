import csv
import io
import uuid

import pytest
from django.utils import timezone

from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import CsvExportFormatStrategy
from tables.import_export.export_tabular_projections.session import (
    SessionTabularProjection,
)
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models.graph_models import Graph, GraphSessionMessage, ScheduleTriggerNode
from tables.models.session_models import Session
from tables.services.schedule_trigger_service import ScheduleTriggerService
from tables.services.session_manager_service import SessionManagerService
from tables.services.trigger_spec import TriggerSpec


class _FakeGraphDump:
    def model_dump(self, mode=None):
        return {}


class _FakeSessionData:
    graph = _FakeGraphDump()


def _stub_publish(monkeypatch, session_manager: SessionManagerService | None = None):
    """Stub the run_session tail (SessionData build + Redis publish) so tests
    don't need a fully built graph or a live Redis connection."""
    sm = session_manager or SessionManagerService()
    monkeypatch.setattr(
        sm, "create_session_data", lambda session, token_budget=None: _FakeSessionData()
    )
    monkeypatch.setattr(
        sm.redis_service,
        "publish_session_data",
        lambda *, session_data, org_id=None: 2,
    )
    return sm


def _add_message(session_id: int) -> None:
    GraphSessionMessage.objects.create(
        session_id=session_id,
        created_at=timezone.now(),
        name="n1",
        execution_order=0,
        message_data={"message_type": "finish"},
        uuid=uuid.uuid4(),
    )


def _export(session_id: int) -> dict:
    data = ExportService(entity_registry).export_entities(
        EntityType.SESSION, [session_id]
    )
    [exported] = data[EntityType.SESSION]
    return exported


def _export_csv_rows(session_id: int) -> list[dict]:
    data = ExportService(entity_registry).export_entities(
        EntityType.SESSION, [session_id]
    )
    response = CsvExportFormatStrategy(SessionTabularProjection()).render(
        data, EntityType.SESSION, "session", str(session_id)
    )
    reader = csv.DictReader(io.StringIO(response.content.decode()))
    return list(reader)


@pytest.mark.django_db
def test_export_entity_json_envelope_includes_principal(
    default_org, regular_user, monkeypatch
):
    graph = Graph.objects.create(name="export-json", org=default_org)
    sm = _stub_publish(monkeypatch)
    session_id = sm.run_session(
        graph_id=graph.id,
        variables={},
        user=regular_user,
        trigger=TriggerSpec.manual(),
    )
    _add_message(session_id)

    exported = _export(session_id)

    assert "session" in exported and "messages" in exported
    principal = exported["session"]["principal"]
    assert principal["kind"] == "user"
    assert principal["user"] == regular_user.id
    assert principal["email"] == regular_user.email
    assert principal["api_key"] is None
    assert len(exported["messages"]) == 1


@pytest.mark.django_db
def test_export_csv_includes_principal_columns_for_user_run(
    default_org, regular_user, monkeypatch
):
    graph = Graph.objects.create(name="export-csv-user", org=default_org)
    sm = _stub_publish(monkeypatch)
    session_id = sm.run_session(
        graph_id=graph.id,
        variables={},
        user=regular_user,
        trigger=TriggerSpec.manual(),
    )
    _add_message(session_id)

    rows = _export_csv_rows(session_id)

    assert len(rows) == 1
    assert rows[0]["principal_kind"] == "user"
    assert rows[0]["principal_user_id"] == str(regular_user.id)
    assert rows[0]["principal_email"] == regular_user.email
    assert rows[0]["principal_api_key_id"] == ""


@pytest.mark.django_db
def test_export_csv_includes_principal_columns_for_trigger_run(
    default_org, monkeypatch
):
    graph = Graph.objects.create(name="export-csv-trigger", org=default_org)
    node = ScheduleTriggerNode.objects.create(graph=graph, node_name="sched")
    _stub_publish(monkeypatch)

    ScheduleTriggerService()._start_session(node)

    session = Session.objects.filter(graph=graph).order_by("-id").first()
    _add_message(session.id)

    rows = _export_csv_rows(session.id)

    assert len(rows) == 1
    assert rows[0]["principal_kind"] == "trigger"
    assert rows[0]["principal_user_id"] == ""
    assert rows[0]["principal_email"] == ""
    assert rows[0]["principal_api_key_id"] == ""
