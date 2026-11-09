"""What each kind of export job writes into its archive, and which lane runs it.

The runner resolves the job's items again with its creator's current rights, writes the
archive the job's definition describes, and names the download. Light exports go to
their own stream, so a large export never holds them up.
"""

import csv
import io
import json
import uuid

import fakeredis
import pytest
from django.utils import timezone

from rbac.models.enums import Permission, ResourceType
from src.shared.redis_streams import (
    TRANSFER_JOB_CONSUMER_GROUP,
    TRANSFER_JOB_LIGHT_CONSUMER_GROUP,
    TRANSFER_JOB_LIGHT_STREAM,
    TRANSFER_JOB_STREAM,
)
from tables.exceptions import ExportEntitiesNotFoundError
from tables.import_export.enums import EntityType
from tables.import_export.export_tabular_projections.session import SessionTabularProjection
from tables.models import (
    ClassificationDecisionTableNode,
    Graph,
    GraphSessionMessage,
    PythonCode,
    PythonCodeTool,
    PythonNode,
    Session,
    TransferJob,
)
from tables.models.knowledge_models import SourceCollection
from tables.services.transfer_jobs.consumer import (
    HeavyTransferJobConsumer,
    LightTransferJobConsumer,
)
from tables.services.transfer_jobs.export_definitions import export_definition
from tables.services.transfer_jobs.job_service import TransferJobService
from tables.services.transfer_jobs.queue import enqueue_transfer_job
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.transfer_job_helpers import run_job

pytestmark = pytest.mark.django_db

FLOW_EXPORT_RIGHTS = {
    ResourceType.FLOWS: Permission.READ | Permission.EXPORT,
    ResourceType.TOOLS: Permission.READ | Permission.EXPORT,
}


@pytest.fixture
def exporter(custom_role_user, acme):
    return custom_role_user(acme, "definitions@example.com", FLOW_EXPORT_RIGHTS)


@pytest.fixture
def flow(acme):
    return Graph.objects.create(name="Support Flow", metadata={"nodes": [], "edges": []}, org=acme)


@pytest.fixture(autouse=True)
def no_queue(monkeypatch):
    # Jobs are run by hand here; the lane tests enqueue explicitly.
    from tables.services.transfer_jobs import job_service

    monkeypatch.setattr(job_service, "enqueue_transfer_job", lambda job: None)


def _start(user, org, main_entity, **validated_data) -> TransferJob:
    return TransferJobService().start_export(
        user=user,
        org_id=org.id,
        definition=export_definition(main_entity),
        validated_data=validated_data,
    )


def _session(flow, *, outputs: list[str]) -> Session:
    session = Session.objects.create(graph=flow, status=Session.SessionStatus.END, variables={})
    for order, output in enumerate(outputs):
        GraphSessionMessage.objects.create(
            session=session,
            created_at=timezone.now(),
            name="python_node",
            execution_order=order,
            node_type="PythonNode",
            message_data={"message_type": "finish", "output": output},
            uuid=uuid.uuid4(),
        )
    return session


# --- tools ----------------------------------------------------------------------------------


def test_a_built_in_tool_export_completes_for_any_org(exporter, acme):
    tool = PythonCodeTool.objects.create(
        name="Web Search",
        description="",
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        org=None,
        built_in=True,
    )
    job = _start(exporter, acme, TransferJob.MainEntity.PYTHON_CODE_TOOL, ids=[tool.id])

    exported = run_job(job.id)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert exported.job.file_name.startswith("python_code_tool_web_search_")
    assert exported.job.file_name.endswith(".zip")
    assert set(exported.members) == {"export.json"}
    assert [entry["name"] for entry in exported.envelope[EntityType.PYTHON_CODE_TOOL]] == [
        "Web Search"
    ]
    assert exported.job.result == {"excluded": []}


def test_a_tool_export_runs_with_the_creators_current_rights(exporter, acme):
    tool = PythonCodeTool.objects.create(
        name="Lookup",
        description="",
        python_code=PythonCode.objects.create(code="x", entrypoint="main"),
        org=acme,
    )
    job = _start(exporter, acme, TransferJob.MainEntity.PYTHON_CODE_TOOL, ids=[tool.id])
    from rbac.models.role import RolePermission

    RolePermission.objects.filter(
        role__organization_users__user=exporter, resource_type=ResourceType.TOOLS
    ).update(permissions=int(Permission.READ))

    exported = run_job(job.id)

    assert (exported.job.status, exported.job.error["code"]) == (
        TransferJob.Status.FAILED,
        "permission_denied",
    )
    assert exported.members == {}


# --- sessions -------------------------------------------------------------------------------


def test_a_json_session_export_holds_sessions_json_only(exporter, acme, flow):
    first = _session(flow, outputs=["hello"])
    second = _session(flow, outputs=["world"])
    job = _start(
        exporter,
        acme,
        TransferJob.MainEntity.SESSION,
        ids=[first.id, second.id],
        export_format="json",
    )

    exported = run_job(job.id)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert set(exported.members) == {"sessions.json"}
    sessions = json.loads(exported.members["sessions.json"])[EntityType.SESSION]
    assert {entry["session"]["id"] for entry in sessions} == {first.id, second.id}
    assert exported.job.display_name == "2 sessions"
    assert exported.job.file_name.startswith("session_bulk_2_")


def test_a_csv_session_export_holds_one_row_per_message(exporter, acme, flow):
    session = _session(flow, outputs=["first output", "=cmd()"])
    job = _start(
        exporter, acme, TransferJob.MainEntity.SESSION, ids=[session.id], export_format="csv"
    )

    exported = run_job(job.id)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert set(exported.members) == {"sessions.csv"}
    reader = csv.DictReader(io.StringIO(exported.members["sessions.csv"].decode("utf-8")))
    assert reader.fieldnames == SessionTabularProjection.FIELDS
    rows = list(reader)
    assert [row["session_id"] for row in rows] == [str(session.id), str(session.id)]
    assert rows[0]["output"] == "first output"
    # A formula a spreadsheet would run is neutralized.
    assert rows[1]["output"] != "=cmd()"
    assert exported.job.display_name == f"Session {session.id}"
    assert exported.job.file_name.startswith(f"session_{session.id}_")


def test_a_session_of_a_flow_binned_after_the_export_started_fails_the_job(exporter, acme, flow):
    session = _session(flow, outputs=["x"])
    job = _start(
        exporter, acme, TransferJob.MainEntity.SESSION, ids=[session.id], export_format="json"
    )
    flow.delete()  # into the recycle bin

    exported = run_job(job.id)

    assert (exported.job.status, exported.job.error["code"]) == (
        TransferJob.Status.FAILED,
        "not_found",
    )


# --- classification decision tables --------------------------------------------------------


def test_a_json_decision_table_export_holds_the_partial_export(exporter, acme, flow):
    node = ClassificationDecisionTableNode.objects.create(graph=flow, node_name="Router")
    job = _start(
        exporter,
        acme,
        TransferJob.MainEntity.CLASSIFICATION_DECISION_TABLE_NODE,
        ids=[node.id],
        export_format="json",
    )

    exported = run_job(job.id)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    assert set(exported.members) == {"export.json"}
    entries = exported.envelope[EntityType.CLASSIFICATION_DECISION_TABLE_NODE]
    assert [entry["node_name"] for entry in entries] == ["Router"]
    assert exported.job.file_name.startswith("CDT_router_")
    assert exported.job.display_name == "Router"


def test_a_csv_decision_table_export_holds_the_readable_csv(exporter, acme, flow):
    node = ClassificationDecisionTableNode.objects.create(graph=flow, node_name="Router")
    job = _start(
        exporter,
        acme,
        TransferJob.MainEntity.CLASSIFICATION_DECISION_TABLE_NODE,
        ids=[node.id],
        export_format="csv",
    )

    exported = run_job(job.id)

    assert exported.job.status == TransferJob.Status.COMPLETED, exported.job.error
    [(member, content)] = exported.members.items()
    assert member.startswith("CDT_router_") and member.endswith(".csv")
    rows = list(csv.reader(io.StringIO(content.decode("utf-8"))))
    assert rows[0] == ["CLASSIFICATION DECISION TABLE"]
    assert rows[1][0] == "Node Name"


# --- lanes ----------------------------------------------------------------------------------


@pytest.fixture
def redis_client():
    client = fakeredis.FakeRedis(decode_responses=True)
    yield client
    client.close()


def _stream_job_ids(redis_client, stream: str) -> list[str]:
    return [fields["job_id"] for _entry_id, fields in redis_client.xrange(stream)]


@pytest.mark.parametrize(
    ("main_entity", "kind", "stream"),
    [
        (TransferJob.MainEntity.FLOW, TransferJob.Kind.EXPORT, TRANSFER_JOB_STREAM),
        (TransferJob.MainEntity.SOURCE_COLLECTION, TransferJob.Kind.EXPORT, TRANSFER_JOB_STREAM),
        (TransferJob.MainEntity.SESSION, TransferJob.Kind.EXPORT, TRANSFER_JOB_STREAM),
        (TransferJob.MainEntity.FLOW, TransferJob.Kind.IMPORT, TRANSFER_JOB_STREAM),
        (TransferJob.MainEntity.SOURCE_COLLECTION, TransferJob.Kind.IMPORT, TRANSFER_JOB_STREAM),
        (TransferJob.MainEntity.PYTHON_CODE_TOOL, TransferJob.Kind.EXPORT, TRANSFER_JOB_LIGHT_STREAM),
        (TransferJob.MainEntity.MCP_TOOL, TransferJob.Kind.EXPORT, TRANSFER_JOB_LIGHT_STREAM),
        (TransferJob.MainEntity.AUDIT_FILTER_PRESET, TransferJob.Kind.EXPORT, TRANSFER_JOB_LIGHT_STREAM),
        (
            TransferJob.MainEntity.CLASSIFICATION_DECISION_TABLE_NODE,
            TransferJob.Kind.EXPORT,
            TRANSFER_JOB_LIGHT_STREAM,
        ),
        (TransferJob.MainEntity.FLOW_NODES, TransferJob.Kind.EXPORT, TRANSFER_JOB_LIGHT_STREAM),
    ],
)
def test_a_job_is_queued_on_the_stream_of_its_lane(
    redis_client, exporter, acme, main_entity, kind, stream
):
    job = TransferJob.objects.create(
        org=acme, created_by=exporter, kind=kind, main_entity=main_entity
    )

    enqueue_transfer_job(job, redis_client=redis_client)

    other = TRANSFER_JOB_LIGHT_STREAM if stream == TRANSFER_JOB_STREAM else TRANSFER_JOB_STREAM
    assert _stream_job_ids(redis_client, stream) == [str(job.id)]
    assert _stream_job_ids(redis_client, other) == []


class RecordingRunner:
    def __init__(self):
        self.job_ids = []

    def run(self, job_id):
        self.job_ids.append(job_id)


def test_each_lanes_consumer_runs_only_its_own_jobs(redis_client, exporter, acme):
    heavy_runner, light_runner = RecordingRunner(), RecordingRunner()
    heavy = HeavyTransferJobConsumer(redis_client, "host-a", runner=heavy_runner)
    light = LightTransferJobConsumer(redis_client, "host-a", runner=light_runner)
    heavy.start()
    light.start()
    flow_job = TransferJob.objects.create(
        org=acme, created_by=exporter, kind="export", main_entity=TransferJob.MainEntity.FLOW
    )
    tool_job = TransferJob.objects.create(
        org=acme,
        created_by=exporter,
        kind="export",
        main_entity=TransferJob.MainEntity.PYTHON_CODE_TOOL,
    )
    enqueue_transfer_job(flow_job, redis_client=redis_client)
    enqueue_transfer_job(tool_job, redis_client=redis_client)

    heavy.process_new(block_milliseconds=None)
    light.process_new(block_milliseconds=None)

    assert heavy_runner.job_ids == [flow_job.id]
    assert light_runner.job_ids == [tool_job.id]
    for stream, group in (
        (TRANSFER_JOB_STREAM, TRANSFER_JOB_CONSUMER_GROUP),
        (TRANSFER_JOB_LIGHT_STREAM, TRANSFER_JOB_LIGHT_CONSUMER_GROUP),
    ):
        assert redis_client.xpending(stream, group)["pending"] == 0


def test_a_flow_export_job_is_named_after_its_flow(exporter, acme, flow):
    job = _start(
        exporter, acme, TransferJob.MainEntity.FLOW, ids=[flow.id], include_knowledge=False
    )

    exported = run_job(job.id)

    assert exported.job.display_name == "Support Flow"
    assert exported.job.file_name.startswith("flow_support_flow_")
    assert exported.envelope["main_entity"] == EntityType.GRAPH


def test_nodes_of_another_orgs_flow_are_no_export_of_the_active_org(exporter, acme, beta):
    # The graphs viewset refuses another org's flow first; this is the check that holds
    # for every other caller of the flow-nodes definition.
    foreign_flow = Graph.objects.create(
        name="Other org flow", metadata={"nodes": [], "edges": []}, org=beta
    )
    node = PythonNode.objects.create(
        graph=foreign_flow, python_code=PythonCode.objects.create(code="x"), node_name="py"
    )

    with pytest.raises(ExportEntitiesNotFoundError):
        _start(
            exporter,
            acme,
            TransferJob.MainEntity.FLOW_NODES,
            ids=[foreign_flow.id],
            python_node_list=[node.id],
        )

    assert not TransferJob.objects.exists()


def test_a_collection_export_job_counts_its_collections(custom_role_user, acme):
    user = custom_role_user(
        acme,
        "collections@example.com",
        {ResourceType.KNOWLEDGE_SOURCES: Permission.READ | Permission.EXPORT},
    )
    ids = [
        SourceCollection.objects.create(collection_name=name, org=acme).collection_id
        for name in ("Handbook", "Policies")
    ]

    job = _start(user, acme, TransferJob.MainEntity.SOURCE_COLLECTION, ids=ids)

    assert job.display_name == "2 knowledge collections"
    assert job.request == {"ids": ids}
