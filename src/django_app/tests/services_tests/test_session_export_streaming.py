"""A session export job writes its archive session by session.

The job loads sessions and messages in chunks, so its query count does not grow with
the number of sessions, and the archive it writes (`sessions.json` / `sessions.csv`)
is the one the in-memory export of the same sessions renders: same sessions, same
order (each session after its sub-sessions in JSON, by session id in CSV), and the
same CSV rows with subflow copies dropped.
"""

import csv
import io
import json
import uuid
from datetime import datetime, timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from rbac.models.enums import Permission, ResourceType
from tables.import_export.enums import EntityType
from tables.import_export.export_format_strategies import (
    CsvExportFormatStrategy,
    write_json_envelope,
)
from tables.import_export.export_tabular_projections.session import SessionTabularProjection
from tables.import_export.registry import entity_registry
from tables.import_export.services.export_service import ExportService
from tables.models import Graph, GraphSessionMessage, Session, TransferJob
from tables.models.session_models import SessionPrincipal, SessionTrigger
from tables.services.transfer_jobs.export_definitions import export_definition
from tables.services.transfer_jobs.job_service import TransferJobService
from tests.helpers import UNRESTRICTED_EXPORT_POLICY
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.transfer_job_helpers import run_job

pytestmark = pytest.mark.django_db

STARTED_AT = datetime.fromisoformat("2026-10-07T13:00:00.000000+00:00")


@pytest.fixture
def exporter(custom_role_user, acme):
    return custom_role_user(
        acme, "streaming@example.com", {ResourceType.FLOWS: Permission.READ | Permission.EXPORT}
    )


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Support Flow", metadata={"nodes": [], "edges": []}, org=acme)


@pytest.fixture
def subflow(acme):
    return Graph.objects.create(name="Inner Flow", metadata={"nodes": [], "edges": []}, org=acme)


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    from tables.services.transfer_jobs import job_service

    monkeypatch.setattr(job_service, "enqueue_transfer_job", lambda job: None)


def _export(user, org, ids, export_format):
    job = TransferJobService().start_export(
        user=user,
        org_id=org.id,
        definition=export_definition(TransferJob.MainEntity.SESSION),
        validated_data={"ids": ids, "export_format": export_format},
    )
    exported = run_job(job.id)
    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    return exported


def _message(session, offset_ms, name, message_data, node_type=""):
    return GraphSessionMessage.objects.create(
        session=session,
        created_at=STARTED_AT + timedelta(milliseconds=offset_ms),
        name=name,
        execution_order=0,
        message_data=message_data,
        node_type=node_type,
        uuid=uuid.uuid4(),
    )


def _session_with_subflow(flow, subflow, *, offset_ms=0) -> tuple[Session, Session, Session]:
    """A root session whose subflow ran a nested subflow, with the copies crew makes.

    The inner finish row lives in the root and is copied into the child and the
    grandchild, as the message store copies subflow rows into every enclosing session.
    """
    root = Session.objects.create(
        graph=flow, status=Session.SessionStatus.END, variables={"big": "x" * 1000}
    )
    SessionPrincipal.objects.create(session=root, kind="user", email="owner@example.com")
    SessionTrigger.objects.create(session=root, trigger_type="manual")
    child = Session.objects.create(graph=subflow, parent_session=root, status="end")
    grandchild = Session.objects.create(graph=subflow, parent_session=child, status="end")

    inner_finish = {"message_type": "finish", "output": "=SUM(A1)", "state": {"variables": {}}}
    _message(root, offset_ms, "agent #1", {"message_type": "start", "input": {}}, "AGENT")
    _message(root, offset_ms + 5, "inner #2", inner_finish, "AGENT")
    _message(root, offset_ms + 9, "agent #1", {"message_type": "finish", "output": "done"}, "AGENT")
    _message(child, offset_ms + 5, "inner #2", inner_finish, "AGENT")
    _message(grandchild, offset_ms + 5, "inner #2", inner_finish, "AGENT")
    return root, child, grandchild


def _in_memory_export(org, ids) -> dict:
    return (
        ExportService(entity_registry)
        .export_entities(EntityType.SESSION, ids, org_id=org.id, policy=UNRESTRICTED_EXPORT_POLICY)
        .data
    )


def _in_memory_csv(data) -> str:
    stream = io.StringIO(newline="")
    CsvExportFormatStrategy(SessionTabularProjection()).write(data, EntityType.SESSION, stream)
    return stream.getvalue()


def _exported_queries(exporter, org, ids, export_format) -> int:
    with CaptureQueriesContext(connection) as queries:
        _export(exporter, org, ids, export_format)
    return len(queries)


@pytest.mark.parametrize("export_format", ["json", "csv"])
def test_queries_do_not_grow_with_the_number_of_sessions(
    exporter, acme, flow, subflow, export_format
):
    few = [_session_with_subflow(flow, subflow)[0].id for _ in range(3)]
    many = [_session_with_subflow(flow, subflow)[0].id for _ in range(30)]

    few_queries = _exported_queries(exporter, acme, few, export_format)
    many_queries = _exported_queries(exporter, acme, many, export_format)

    assert many_queries == few_queries
    assert few_queries <= 20


def test_json_export_holds_every_sub_session_after_its_parent_tree(exporter, acme, flow, subflow):
    lone = Session.objects.create(graph=flow, status=Session.SessionStatus.ERROR)
    root, child, grandchild = _session_with_subflow(flow, subflow)

    exported = _export(exporter, acme, [lone.id, root.id], "json")

    envelope = json.loads(exported.members["sessions.json"])
    assert [entry["session"]["id"] for entry in envelope[EntityType.SESSION]] == [
        lone.id,
        grandchild.id,
        child.id,
        root.id,
    ]
    assert (envelope["main_entity"], envelope["version"]) == ("Session", 6)
    root_entry = envelope[EntityType.SESSION][-1]
    assert root_entry["session"]["graph_name"] == "Support Flow"
    assert root_entry["session"]["principal"]["email"] == "owner@example.com"
    assert root_entry["session"]["trigger_type"] == "manual"
    assert [message["name"] for message in root_entry["messages"]] == [
        "agent #1",
        "inner #2",
        "agent #1",
    ]
    assert "variables" not in root_entry["session"]


def test_csv_export_drops_subflow_copies_of_an_exported_root(exporter, acme, flow, subflow):
    root, child, grandchild = _session_with_subflow(flow, subflow)

    exported = _export(exporter, acme, [root.id], "csv")

    rows = list(csv.DictReader(io.StringIO(exported.members["sessions.csv"].decode("utf-8"))))
    assert [(row["session_id"], row["node_name"]) for row in rows] == [
        (str(root.id), "agent #1"),
        (str(root.id), "inner #2"),
        (str(root.id), "agent #1"),
    ]
    assert rows[1]["output"] == "'=SUM(A1)"
    assert rows[2]["duration_ms"] == "9"


def test_csv_export_of_a_child_alone_keeps_its_copy_and_drops_the_grandchilds(
    exporter, acme, flow, subflow
):
    _root, child, _grandchild = _session_with_subflow(flow, subflow)

    exported = _export(exporter, acme, [child.id], "csv")

    rows = list(csv.DictReader(io.StringIO(exported.members["sessions.csv"].decode("utf-8"))))
    assert [(row["session_id"], row["flow_name"]) for row in rows] == [(str(child.id), "Inner Flow")]


@pytest.mark.parametrize(
    "pick",
    [
        pytest.param(lambda trees: [trees[1][0].id, trees[0][0].id], id="roots-out-of-order"),
        pytest.param(lambda trees: [trees[0][1].id, trees[0][0].id], id="child-before-root"),
        pytest.param(lambda trees: [trees[0][2].id, trees[1][1].id], id="sub-sessions-only"),
    ],
)
def test_archive_matches_the_in_memory_export(exporter, acme, flow, subflow, pick):
    trees = [_session_with_subflow(flow, subflow, offset_ms=offset) for offset in (0, 1000)]
    ids = pick(trees)

    as_json = _export(exporter, acme, ids, "json").members["sessions.json"].decode("utf-8")
    as_csv = _export(exporter, acme, ids, "csv").members["sessions.csv"].decode("utf-8")

    expected = _in_memory_export(acme, ids)
    assert as_json == json.dumps(expected, indent=4)
    assert as_csv == _in_memory_csv(expected)


@pytest.mark.parametrize("entries", [[], [{"a": [1, {"b": "x\ny"}]}], [{"a": 1}, {"b": {}}, {"c": []}]])
def test_streamed_envelope_is_the_text_json_dump_writes(entries):
    stream = io.StringIO()

    write_json_envelope(EntityType.SESSION, iter(entries), stream)

    expected = {EntityType.SESSION: entries, "main_entity": EntityType.SESSION, "version": 6}
    assert stream.getvalue() == json.dumps(expected, indent=4)
