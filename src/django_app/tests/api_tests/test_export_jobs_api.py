"""Starting every kind of export as a background job, and listing and removing one's jobs.

Each `export-jobs` action answers 202 with a queued job that carries the request and the
name the job list shows; an item the caller may not export from the active organization
is a 404 and leaves no job. The job list and removal see only the caller's own jobs in
the active organization.
"""

import io
import threading
import time
import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from rbac.models.enums import Permission, ResourceType
from tables.models import (
    ClassificationDecisionTableNode,
    Graph,
    McpTool,
    PythonCode,
    PythonCodeTool,
    PythonNode,
    Session,
    TransferJob,
)
from tables.models.audit_filter_preset_models import AuditFilterPreset
from tables.models.user import User
from tables.services.transfer_jobs import job_service
from tables.services.transfer_jobs.archive_store import TransferArchiveStore
from tables.services.transfer_jobs.runner import TransferJobRunner
from tables.serializers.transfer_job_serializers import SESSION_EXPORT_MAX_IDS
from tables.views import transfer_job_views
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403
from tests.storage_backend_fake import FakeStorageBackend

pytestmark = pytest.mark.django_db

EVERY_EXPORT_RIGHT = {
    ResourceType.FLOWS: Permission.READ | Permission.EXPORT,
    ResourceType.TOOLS: Permission.READ | Permission.EXPORT,
    ResourceType.AUDIT: Permission.READ,
}


@pytest.fixture(autouse=True)
def enqueued(monkeypatch):
    """Job ids handed to the background consumers, in order; no Redis needed."""
    job_ids = []
    monkeypatch.setattr(job_service, "enqueue_transfer_job", lambda job: job_ids.append(job.id))
    return job_ids


@pytest.fixture
def client_in(client_as):
    def _client(user, org):
        client = client_as(user)
        client.credentials(HTTP_X_ORGANIZATION_ID=str(org.id))
        return client

    return _client


@pytest.fixture
def exporter(custom_role_user, acme):
    return custom_role_user(acme, "every-export@example.com", EVERY_EXPORT_RIGHT)


def _flow(org, name="Support") -> Graph:
    return Graph.objects.create(name=name, metadata={"nodes": [], "edges": []}, org=org)


def _python_tool(org, name="Lookup", built_in=False) -> PythonCodeTool:
    return PythonCodeTool.objects.create(
        name=name,
        description="",
        python_code=PythonCode.objects.create(code="def main(): return 1", entrypoint="main"),
        org=org,
        built_in=built_in,
    )


def _mcp_tool(org, name="Search") -> McpTool:
    return McpTool.objects.create(
        org=org, name=name, transport="https://example.com/mcp", tool_name="search"
    )


def _preset(org, author=None, name="Failed runs", shared=True) -> AuditFilterPreset:
    """A preset of `author`, or of a colleague made here when `author` is None."""
    if author is None:
        author = User.objects.create_user(
            email=f"preset-author-{uuid.uuid4().hex[:8]}@example.com", password="StrongPass123!"
        )
    return AuditFilterPreset.objects.create(
        org=org,
        created_by=author,
        name=name,
        filter_body={"query": "status = failed"},
        is_shared=shared,
    )


def _session(org, flow=None) -> Session:
    return Session.objects.create(
        graph=flow or _flow(org, f"Sessions flow {uuid.uuid4().hex[:8]}"),
        status=Session.SessionStatus.END,
        variables={},
    )


def _cdt_node(org, name="Router") -> ClassificationDecisionTableNode:
    return ClassificationDecisionTableNode.objects.create(graph=_flow(org), node_name=name)


def _python_node(flow) -> PythonNode:
    return PythonNode.objects.create(
        graph=flow, python_code=PythonCode.objects.create(code="x"), node_name="py"
    )


# --- one row per export definition ----------------------------------------------------------


def _python_tool_case(org, author):
    tool = _python_tool(org)
    return "/api/python-code-tool/export-jobs/", {"ids": [tool.id]}, {"ids": [tool.id]}, "Lookup"


def _built_in_tool_case(org, author):
    tool = _python_tool(None, name="Built-in lookup", built_in=True)
    return (
        "/api/python-code-tool/export-jobs/",
        {"ids": [tool.id]},
        {"ids": [tool.id]},
        "Built-in lookup",
    )


def _mcp_tools_case(org, author):
    ids = [_mcp_tool(org, "One").id, _mcp_tool(org, "Two").id]
    return "/api/mcp-tools/export-jobs/", {"ids": ids}, {"ids": ids}, "2 MCP tools"


def _colleagues_shared_preset_case(org, author):
    preset = _preset(org)
    return (
        "/api/audit-filter-presets/export-jobs/",
        {"ids": [preset.id]},
        {"ids": [preset.id]},
        "Failed runs",
    )


def _sessions_case(org, author):
    ids = [_session(org).id, _session(org).id]
    return (
        "/api/sessions/export-jobs/",
        {"ids": ids, "export_format": "csv"},
        {"ids": ids, "export_format": "csv"},
        "2 sessions",
    )


def _sessions_by_filter_case(org, author):
    flow = _flow(org, "Filtered")
    matching = _session(org, flow)
    _session(org)  # another flow's session
    return (
        "/api/sessions/export-jobs/",
        {"graph_id": flow.id},
        {"ids": [matching.id], "export_format": "json"},
        f"Session {matching.id}",
    )


def _cdt_case(org, author):
    node = _cdt_node(org)
    return (
        "/api/classification-decision-table-node/export-jobs/",
        {"ids": [node.id], "export_format": "csv"},
        {"ids": [node.id], "export_format": "csv"},
        "Router",
    )


def _flow_nodes_case(org, author):
    flow = _flow(org, "Editor flow")
    node = _python_node(flow)
    return (
        f"/api/graphs/{flow.id}/partial-export-jobs/",
        {"python_node_list": [node.id]},
        {"ids": [flow.id], "nodes": {"python_node_list": [node.id]}, "edge_list": []},
        "1 node from Editor flow",
    )


@pytest.mark.parametrize(
    ("make_case", "main_entity"),
    [
        pytest.param(_python_tool_case, "PythonCodeTool", id="python tool"),
        pytest.param(_built_in_tool_case, "PythonCodeTool", id="built-in python tool"),
        pytest.param(_mcp_tools_case, "MCPTool", id="mcp tools"),
        pytest.param(_colleagues_shared_preset_case, "AuditFilterPreset", id="shared preset"),
        pytest.param(_sessions_case, "Session", id="sessions by id"),
        pytest.param(_sessions_by_filter_case, "Session", id="sessions by filter"),
        pytest.param(_cdt_case, "ClassificationDecisionTableNode", id="decision table"),
        pytest.param(_flow_nodes_case, "FlowNodes", id="flow nodes"),
    ],
)
def test_an_export_job_is_queued_with_its_request_and_name(
    client_in,
    exporter,
    acme,
    enqueued,
    django_capture_on_commit_callbacks,
    make_case,
    main_entity,
):
    url, body, stored_request, display_name = make_case(acme, exporter)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_in(exporter, acme).post(url, body, format="json")

    assert response.status_code == 202, response.content
    job = TransferJob.objects.get(pk=response.json()["job_id"])
    assert (job.kind, job.status, job.main_entity, job.org_id, job.created_by_id) == (
        TransferJob.Kind.EXPORT,
        TransferJob.Status.QUEUED,
        main_entity,
        acme.id,
        exporter.id,
    )
    assert job.request == stored_request
    assert job.display_name == display_name
    assert enqueued == [job.id]


@pytest.mark.parametrize(
    ("url", "make_body"),
    [
        pytest.param(
            "/api/python-code-tool/export-jobs/",
            lambda org: {"ids": [_python_tool(org).id]},
            id="python tool",
        ),
        pytest.param(
            "/api/mcp-tools/export-jobs/", lambda org: {"ids": [_mcp_tool(org).id]}, id="mcp tool"
        ),
        pytest.param(
            "/api/audit-filter-presets/export-jobs/",
            lambda org: {"ids": [_preset(org).id]},
            id="audit preset",
        ),
        pytest.param(
            "/api/sessions/export-jobs/", lambda org: {"ids": [_session(org).id]}, id="session"
        ),
        pytest.param(
            "/api/classification-decision-table-node/export-jobs/",
            lambda org: {"ids": [_cdt_node(org).id]},
            id="decision table",
        ),
    ],
)
def test_another_orgs_item_is_not_found_and_queues_nothing(
    client_in, exporter, acme, beta, enqueued, url, make_body
):
    response = client_in(exporter, acme).post(url, make_body(beta), format="json")

    assert response.status_code == 404, response.content
    assert response.json()["code"] == "export_entities_not_found"
    assert not TransferJob.objects.exists()
    assert enqueued == []


def test_nodes_of_another_orgs_flow_are_not_found(client_in, exporter, acme, beta, enqueued):
    flow = _flow(beta)

    response = client_in(exporter, acme).post(
        f"/api/graphs/{flow.id}/partial-export-jobs/",
        {"python_node_list": [_python_node(flow).id]},
        format="json",
    )

    assert response.status_code == 404
    assert not TransferJob.objects.exists()


def test_sessions_matching_no_filter_of_another_org_are_not_found(
    client_in, exporter, acme, beta, enqueued
):
    foreign_flow = _flow(beta)
    _session(beta, foreign_flow)

    by_flow = client_in(exporter, acme).post(
        "/api/sessions/export-jobs/", {"graph_id": foreign_flow.id}, format="json"
    )
    everything = client_in(exporter, acme).post("/api/sessions/export-jobs/", {}, format="json")

    assert by_flow.status_code == everything.status_code == 404
    assert not TransferJob.objects.exists()


def test_a_colleagues_private_preset_is_not_found(
    client_in, exporter, custom_role_user, acme, enqueued
):
    author = custom_role_user(acme, "preset-author@example.com", EVERY_EXPORT_RIGHT)
    private = _preset(acme, author, shared=False)

    response = client_in(exporter, acme).post(
        "/api/audit-filter-presets/export-jobs/", {"ids": [private.id]}, format="json"
    )

    assert response.status_code == 404
    assert not TransferJob.objects.exists()


def _nodes_of_a_new_flow(org) -> tuple[str, dict]:
    flow = _flow(org, "Editor flow")
    return f"/api/graphs/{flow.id}/partial-export-jobs/", {"python_node_list": [_python_node(flow).id]}


@pytest.mark.parametrize(
    ("rights", "make_request"),
    [
        pytest.param(
            {ResourceType.TOOLS: Permission.READ},
            lambda org: ("/api/python-code-tool/export-jobs/", {"ids": [_python_tool(org).id]}),
            id="tools without export, python tool",
        ),
        pytest.param(
            {ResourceType.TOOLS: Permission.READ},
            lambda org: ("/api/mcp-tools/export-jobs/", {"ids": [_mcp_tool(org).id]}),
            id="tools without export, mcp tool",
        ),
        pytest.param(
            {ResourceType.FLOWS: Permission.READ},
            lambda org: ("/api/sessions/export-jobs/", {"ids": [_session(org).id]}),
            id="flows without export, sessions",
        ),
        pytest.param(
            {ResourceType.FLOWS: Permission.READ},
            lambda org: (
                "/api/classification-decision-table-node/export-jobs/",
                {"ids": [_cdt_node(org).id]},
            ),
            id="flows without export, decision table",
        ),
        pytest.param(
            {ResourceType.FLOWS: Permission.READ},
            _nodes_of_a_new_flow,
            id="flows without export, flow nodes",
        ),
        pytest.param(
            {ResourceType.FLOWS: Permission.READ | Permission.EXPORT},
            lambda org: ("/api/audit-filter-presets/export-jobs/", {"ids": [_preset(org).id]}),
            id="no audit read",
        ),
    ],
)
def test_an_export_job_needs_the_definitions_right(
    client_in, custom_role_user, acme, enqueued, rights, make_request
):
    user = custom_role_user(acme, "short-of-rights@example.com", rights)
    url, body = make_request(acme)

    response = client_in(user, acme).post(url, body, format="json")

    assert response.status_code == 403
    assert not TransferJob.objects.exists()


def test_audit_read_alone_exports_and_downloads_a_preset(
    client_in, custom_role_user, acme, enqueued, monkeypatch
):
    # Presets are gated on AUDIT read for every action; the audit resource grants no EXPORT.
    user = custom_role_user(acme, "audit-reader@example.com", {ResourceType.AUDIT: Permission.READ})
    preset = _preset(acme, user, shared=False)
    client = client_in(user, acme)
    response = client.post(
        "/api/audit-filter-presets/export-jobs/", {"ids": [preset.id]}, format="json"
    )
    job = TransferJob.objects.get(pk=response.json()["job_id"])
    backend = FakeStorageBackend()
    key = TransferArchiveStore(backend=backend).upload_file(job.id, "export.zip", io.BytesIO(b"zip"))
    TransferJob.objects.filter(pk=job.pk).update(
        status=TransferJob.Status.COMPLETED, archive_key=key, file_name="presets.zip"
    )
    monkeypatch.setattr(
        transfer_job_views, "TransferArchiveStore", lambda: TransferArchiveStore(backend=backend)
    )

    download = client.get(f"/api/transfer-jobs/{job.id}/download/")

    assert response.status_code == 202
    assert download.status_code == 200
    assert b"".join(download.streaming_content) == b"zip"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"ids": [1], "graph_id": 1}, id="ids and filters"),
        pytest.param({"ids": [1], "export_format": "xml"}, id="unknown format"),
        pytest.param({"ids": list(range(1, SESSION_EXPORT_MAX_IDS + 2))}, id="too many ids"),
        pytest.param({"ids": []}, id="no ids"),
    ],
)
def test_an_invalid_session_export_request_queues_nothing(
    client_in, exporter, acme, enqueued, body
):
    response = client_in(exporter, acme).post("/api/sessions/export-jobs/", body, format="json")

    assert response.status_code == 400, response.content
    assert not TransferJob.objects.exists()


def test_a_session_export_takes_up_to_the_id_cap(client_in, exporter, acme, enqueued):
    session = _session(acme)
    # Ids past the first are no sessions: the cap is checked before they are looked up.
    body = {"ids": [session.id, *range(10**9, 10**9 + SESSION_EXPORT_MAX_IDS - 1)]}

    response = client_in(exporter, acme).post("/api/sessions/export-jobs/", body, format="json")

    assert response.status_code == 404
    assert response.json()["code"] == "export_entities_not_found"


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"ids": [1, 2]}, id="two nodes"),
        pytest.param({"ids": [1], "export_format": "pdf"}, id="unknown format"),
    ],
)
def test_an_invalid_decision_table_export_request_queues_nothing(
    client_in, exporter, acme, enqueued, body
):
    response = client_in(exporter, acme).post(
        "/api/classification-decision-table-node/export-jobs/", body, format="json"
    )

    assert response.status_code == 400
    assert not TransferJob.objects.exists()


def test_a_flow_nodes_export_needs_at_least_one_node(client_in, exporter, acme, enqueued):
    flow = _flow(acme)

    response = client_in(exporter, acme).post(
        f"/api/graphs/{flow.id}/partial-export-jobs/", {"edge_list": [1]}, format="json"
    )

    assert response.status_code == 400
    assert not TransferJob.objects.exists()


def test_a_session_export_with_ids_and_filters_names_the_filters_it_refused(
    client_in, exporter, acme, enqueued
):
    session = _session(acme)

    response = client_in(exporter, acme).post(
        "/api/sessions/export-jobs/",
        {"ids": [session.id], "graph_id": session.graph_id, "status": ["end"]},
        format="json",
    )

    assert response.status_code == 400
    assert response.json()["message"].endswith("(got graph_id, status).")
    assert not TransferJob.objects.exists()


def test_a_system_api_key_is_refused_before_any_session_is_selected(
    api_client, default_org, env_api_key, enqueued
):
    flow = _flow(default_org)
    _session(default_org, flow)
    raw_key, _key = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id))

    with CaptureQueriesContext(connection) as queries:
        response = api_client.post(
            "/api/sessions/export-jobs/", {"graph_id": flow.id}, format="json"
        )

    assert response.status_code == 403, response.content
    assert response.json()["code"] == "transfer_job_requires_user"
    assert not TransferJob.objects.exists()
    assert enqueued == []
    # Matching sessions by filters reads up to the id cap; a caller who could never own
    # the job must not cost that.
    assert not [query for query in queries.captured_queries if '"tables_session"' in query["sql"]]


# --- the job list ----------------------------------------------------------------------------


def _job(user, org, *, created_ago_minutes=0, **fields) -> TransferJob:
    job = TransferJob.objects.create(
        org=org,
        created_by=user,
        kind=fields.pop("kind", TransferJob.Kind.EXPORT),
        main_entity=fields.pop("main_entity", TransferJob.MainEntity.FLOW),
        **fields,
    )
    TransferJob.objects.filter(pk=job.pk).update(
        created_at=timezone.now() - timedelta(minutes=created_ago_minutes)
    )
    return job


def _listed_ids(response) -> list[str]:
    assert response.status_code == 200, response.content
    return [job["id"] for job in response.json()["results"]]


def test_the_list_shows_the_callers_jobs_in_the_active_org_newest_first(
    client_in, exporter, custom_role_user, acme, beta
):
    oldest = _job(exporter, acme, created_ago_minutes=30, display_name="old flows")
    newest = _job(exporter, acme, created_ago_minutes=1, display_name="Support")
    middle = _job(exporter, acme, created_ago_minutes=10, kind=TransferJob.Kind.IMPORT)
    colleague = custom_role_user(acme, "colleague@example.com", EVERY_EXPORT_RIGHT)
    _job(colleague, acme)
    _job(exporter, beta)

    response = client_in(exporter, acme).get("/api/transfer-jobs/")

    assert _listed_ids(response) == [str(newest.id), str(middle.id), str(oldest.id)]
    assert response.json()["count"] == 3
    assert response.json()["results"][0]["display_name"] == "Support"


def test_the_list_filters_by_any_of_several_statuses_and_by_kind(client_in, exporter, acme):
    queued = _job(exporter, acme, created_ago_minutes=3, status=TransferJob.Status.QUEUED)
    running = _job(exporter, acme, created_ago_minutes=2, status=TransferJob.Status.RUNNING)
    _job(exporter, acme, status=TransferJob.Status.COMPLETED)
    running_import = _job(
        exporter, acme, status=TransferJob.Status.RUNNING, kind=TransferJob.Kind.IMPORT
    )
    client = client_in(exporter, acme)

    unfinished = client.get("/api/transfer-jobs/?status=queued&status=running")
    unfinished_exports = client.get("/api/transfer-jobs/?status=queued&status=running&kind=export")

    assert _listed_ids(unfinished) == [str(running_import.id), str(running.id), str(queued.id)]
    assert _listed_ids(unfinished_exports) == [str(running.id), str(queued.id)]


@pytest.mark.parametrize("query", ["status=paused", "kind=copy"])
def test_an_unknown_list_filter_value_is_refused(client_in, exporter, acme, query):
    response = client_in(exporter, acme).get(f"/api/transfer-jobs/?{query}")

    assert response.status_code == 400


def test_the_list_is_paginated(client_in, exporter, acme):
    for minutes in range(3):
        _job(exporter, acme, created_ago_minutes=minutes)

    response = client_in(exporter, acme).get("/api/transfer-jobs/?limit=2")

    assert response.json()["count"] == 3
    assert len(response.json()["results"]) == 2


def test_a_system_api_key_lists_no_jobs(api_client, default_org, env_api_key, regular_user):
    _job(regular_user, default_org)
    raw_key, _key = env_api_key
    api_client.credentials(HTTP_X_API_KEY=raw_key, HTTP_X_ORGANIZATION_ID=str(default_org.id))

    response = api_client.get("/api/transfer-jobs/")

    assert _listed_ids(response) == []


# --- removing a job --------------------------------------------------------------------------


@pytest.fixture
def stored(monkeypatch):
    """The storage the job removal deletes archives from."""
    backend = FakeStorageBackend()
    monkeypatch.setattr(
        job_service, "TransferArchiveStore", lambda: TransferArchiveStore(backend=backend)
    )
    return backend


def _with_archive(job: TransferJob, backend: FakeStorageBackend) -> TransferJob:
    key = TransferArchiveStore(backend=backend).upload_file(job.id, "export.zip", io.BytesIO(b"z"))
    TransferJob.objects.filter(pk=job.pk).update(archive_key=key)
    return job


@pytest.mark.parametrize(
    ("status", "kind"),
    [
        (TransferJob.Status.QUEUED, TransferJob.Kind.EXPORT),
        (TransferJob.Status.QUEUED, TransferJob.Kind.IMPORT),
        (TransferJob.Status.COMPLETED, TransferJob.Kind.EXPORT),
        (TransferJob.Status.FAILED, TransferJob.Kind.IMPORT),
    ],
)
def test_a_job_that_is_not_running_is_removed_with_its_archive(
    client_in, exporter, acme, stored, django_capture_on_commit_callbacks, status, kind
):
    job = _job(exporter, acme, status=status, kind=kind)
    key = TransferArchiveStore(backend=stored).upload_file(job.id, "export.zip", io.BytesIO(b"z"))
    TransferJob.objects.filter(pk=job.pk).update(archive_key=key)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_in(exporter, acme).delete(f"/api/transfer-jobs/{job.id}/")

    assert response.status_code == 204
    assert not TransferJob.objects.filter(pk=job.pk).exists()
    assert stored.objects == {}


def test_a_running_job_is_not_removed(client_in, exporter, acme, stored):
    job = _job(exporter, acme, status=TransferJob.Status.RUNNING)

    response = client_in(exporter, acme).delete(f"/api/transfer-jobs/{job.id}/")

    assert response.status_code == 409
    assert response.json()["code"] == "job_running"
    assert TransferJob.objects.filter(pk=job.pk).exists()


class _StorageDownFor(FakeStorageBackend):
    """Storage that cannot delete the files of the given jobs."""

    def __init__(self, *job_ids):
        super().__init__()
        self.down_for = {str(job_id) for job_id in job_ids}

    def delete_prefix(self, prefix: str) -> None:
        if any(job_id in prefix for job_id in self.down_for):
            raise RuntimeError("storage down")
        super().delete_prefix(prefix)


def test_a_removed_job_stays_removed_when_its_archive_cannot_be_deleted(
    client_in, exporter, acme, monkeypatch, django_capture_on_commit_callbacks
):
    job = _job(exporter, acme, status=TransferJob.Status.COMPLETED)
    backend = _StorageDownFor(job.id)
    _with_archive(job, backend)
    monkeypatch.setattr(
        job_service, "TransferArchiveStore", lambda: TransferArchiveStore(backend=backend)
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = client_in(exporter, acme).delete(f"/api/transfer-jobs/{job.id}/")

    # The sweep deletes an archive left without its job.
    assert response.status_code == 204
    assert not TransferJob.objects.filter(pk=job.pk).exists()
    assert any(str(job.id) in key for key in backend.objects)


@pytest.mark.parametrize("who", ["colleague in the same org", "creator in another org"])
def test_only_the_creator_in_its_org_removes_a_job(
    client_in, exporter, custom_role_user, acme, beta, stored, role_org_admin, who
):
    from rbac.models import OrganizationUser

    job = _job(exporter, acme, status=TransferJob.Status.COMPLETED)
    if who == "colleague in the same org":
        client = client_in(custom_role_user(acme, "colleague@example.com", EVERY_EXPORT_RIGHT), acme)
    else:
        OrganizationUser.objects.create(user=exporter, org=beta, role=role_org_admin)
        client = client_in(exporter, beta)

    response = client.delete(f"/api/transfer-jobs/{job.id}/")

    assert response.status_code == 404
    assert TransferJob.objects.filter(pk=job.pk).exists()


def test_an_unknown_job_cannot_be_removed(client_in, exporter, acme, stored):
    response = client_in(exporter, acme).delete(f"/api/transfer-jobs/{uuid.uuid4()}/")

    assert response.status_code == 404


def test_a_queued_job_removed_before_it_ran_is_never_run(client_in, exporter, acme, stored):
    class UntouchableStore:
        def __getattr__(self, name):
            raise AssertionError(f"the runner used the archive store ({name})")

    tool = _python_tool(acme)
    client = client_in(exporter, acme)
    job_id = client.post(
        "/api/python-code-tool/export-jobs/", {"ids": [tool.id]}, format="json"
    ).json()["job_id"]
    assert client.delete(f"/api/transfer-jobs/{job_id}/").status_code == 204

    TransferJobRunner(store=UntouchableStore()).run(uuid.UUID(job_id))

    assert not TransferJob.objects.filter(pk=job_id).exists()


# --- clearing the job list -------------------------------------------------------------------

CLEAR_URL = "/api/transfer-jobs/clear/"


def test_clearing_removes_every_job_that_is_not_running_with_its_archive(
    client_in, exporter, acme, stored, django_capture_on_commit_callbacks
):
    removable = [
        _with_archive(_job(exporter, acme, status=status, kind=kind), stored)
        for status, kind in [
            (TransferJob.Status.QUEUED, TransferJob.Kind.EXPORT),
            (TransferJob.Status.QUEUED, TransferJob.Kind.IMPORT),
            (TransferJob.Status.COMPLETED, TransferJob.Kind.EXPORT),
            (TransferJob.Status.FAILED, TransferJob.Kind.IMPORT),
        ]
    ]
    running = _with_archive(_job(exporter, acme, status=TransferJob.Status.RUNNING), stored)

    with django_capture_on_commit_callbacks(execute=True):
        response = client_in(exporter, acme).post(CLEAR_URL)

    assert response.status_code == 200
    assert response.json() == {"deleted": 4}
    assert set(TransferJob.objects.values_list("pk", flat=True)) == {running.pk}
    assert not any(str(job.id) in key for job in removable for key in stored.objects)
    # The running job keeps the files it is writing.
    assert any(str(running.id) in key for key in stored.objects)


def test_clearing_leaves_other_users_and_other_orgs_jobs_alone(
    client_in, exporter, custom_role_user, acme, beta, stored, role_org_admin
):
    from rbac.models import OrganizationUser

    colleague = custom_role_user(acme, "colleague@example.com", EVERY_EXPORT_RIGHT)
    stranger = custom_role_user(beta, "stranger@example.com", EVERY_EXPORT_RIGHT)
    OrganizationUser.objects.create(user=exporter, org=beta, role=role_org_admin)
    mine = _job(exporter, acme, status=TransferJob.Status.COMPLETED)
    kept = [
        _job(colleague, acme, status=TransferJob.Status.COMPLETED),
        _job(stranger, beta, status=TransferJob.Status.FAILED),
        # The caller's own job, but in the org that is not active.
        _job(exporter, beta, status=TransferJob.Status.COMPLETED),
    ]

    response = client_in(exporter, acme).post(CLEAR_URL)

    assert response.json() == {"deleted": 1}
    assert not TransferJob.objects.filter(pk=mine.pk).exists()
    assert set(TransferJob.objects.values_list("pk", flat=True)) == {job.pk for job in kept}


@pytest.mark.parametrize(
    "statuses",
    [
        pytest.param([], id="no jobs"),
        pytest.param([TransferJob.Status.RUNNING], id="only a running job"),
    ],
)
def test_clearing_with_nothing_to_remove_answers_zero(client_in, exporter, acme, stored, statuses):
    for status in statuses:
        _job(exporter, acme, status=status)

    response = client_in(exporter, acme).post(CLEAR_URL)

    assert response.status_code == 200
    assert response.json() == {"deleted": 0}
    assert TransferJob.objects.count() == len(statuses)


def test_a_queued_job_cleared_before_it_ran_is_never_run(client_in, exporter, acme, stored):
    class UntouchableStore:
        def __getattr__(self, name):
            raise AssertionError(f"the runner used the archive store ({name})")

    tool = _python_tool(acme)
    client = client_in(exporter, acme)
    job_id = client.post(
        "/api/python-code-tool/export-jobs/", {"ids": [tool.id]}, format="json"
    ).json()["job_id"]
    assert client.post(CLEAR_URL).json() == {"deleted": 1}

    TransferJobRunner(store=UntouchableStore()).run(uuid.UUID(job_id))

    assert not TransferJob.objects.filter(pk=job_id).exists()


def test_clearing_needs_credentials(api_client, exporter, acme, stored):
    job = _job(exporter, acme, status=TransferJob.Status.COMPLETED)

    response = api_client.post(CLEAR_URL)

    assert response.status_code == 401
    assert TransferJob.objects.filter(pk=job.pk).exists()


def test_clearing_deletes_the_other_archives_when_one_cannot_be_deleted(
    client_in, exporter, acme, monkeypatch, django_capture_on_commit_callbacks
):
    stuck, other = (_job(exporter, acme, status=TransferJob.Status.COMPLETED) for _ in range(2))
    backend = _StorageDownFor(stuck.id)
    for job in (stuck, other):
        _with_archive(job, backend)
    monkeypatch.setattr(
        job_service, "TransferArchiveStore", lambda: TransferArchiveStore(backend=backend)
    )

    with django_capture_on_commit_callbacks(execute=True):
        response = client_in(exporter, acme).post(CLEAR_URL)

    assert response.json() == {"deleted": 2}
    assert not TransferJob.objects.exists()
    assert any(str(stuck.id) in key for key in backend.objects)
    assert not any(str(other.id) in key for key in backend.objects)


# --- removal against the runner, on two real connections -------------------------------------


def _wait_until_blocked_or_done(worker: threading.Thread, timeout: float = 10) -> None:
    """Return once `worker` finished or another connection waits on a row lock."""
    deadline = time.monotonic() + timeout
    while worker.is_alive() and time.monotonic() < deadline:
        with connection.cursor() as cursor:
            cursor.execute("SELECT count(*) FROM pg_locks WHERE NOT granted")
            if cursor.fetchone()[0]:
                return
        time.sleep(0.01)
    if worker.is_alive():
        pytest.fail("the runner neither finished nor waited on a lock")


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize(
    "remove",
    [
        pytest.param(lambda client, job_id: client.delete(f"/api/transfer-jobs/{job_id}/"), id="one"),
        pytest.param(lambda client, job_id: client.post(CLEAR_URL), id="clear"),
    ],
)
def test_the_runner_cannot_start_a_job_while_it_is_being_removed(
    client_in, exporter, acme, stored, remove
):
    client = client_in(exporter, acme)
    job_id = client.post(
        "/api/python-code-tool/export-jobs/", {"ids": [_python_tool(acme).id]}, format="json"
    ).json()["job_id"]
    runner_errors = []

    def run_job():
        try:
            TransferJobRunner(store=TransferArchiveStore(backend=stored)).run(uuid.UUID(job_id))
        except Exception as error:  # surfaced by the assertion below
            runner_errors.append(error)
        finally:
            connection.close()

    runner = threading.Thread(target=run_job)

    def start_the_runner_once_the_job_is_read(execute, sql, params, many, context):
        # Between the removal reading the job and deleting it, the runner is handed the job.
        result = execute(sql, params, many, context)
        if (
            runner.ident is None
            and sql.lstrip().upper().startswith("SELECT")
            and '"tables_transferjob"' in sql
        ):
            runner.start()
            _wait_until_blocked_or_done(runner)
        return result

    with connection.execute_wrapper(start_the_runner_once_the_job_is_read):
        response = remove(client, job_id)
    runner.join(timeout=10)

    assert response.status_code in (200, 204), response.content
    assert not runner.is_alive()
    assert runner_errors == []
    assert not TransferJob.objects.filter(pk=job_id).exists()
    # A run would have uploaded the export's archive.
    assert stored.objects == {}, "the runner exported a job that was being removed"
