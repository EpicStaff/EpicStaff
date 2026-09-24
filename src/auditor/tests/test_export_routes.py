import os

# The auditor settings module requires these at import time (no defaults) -
# set dummy values before anything under app.* gets imported, so this module
# is runnable on its own without a real .env file (mirrors what docker-compose injects).
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")

import csv
import io
import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import app.services.search_pipeline as search_pipeline
from app.controllers.export_routes import build_export_router
from app.core.security import verify_user_jwt
from app.core import settings
from app.domains.sessions.domain import SESSIONS
from app.services.export_job_service import ExportJobService
from src.shared.models import SessionAuditEvent
from tests._fakes import InMemoryFakeRepository

DEFAULT_CLAIMS = {
    "org_id": 7,
    "user_id": 42,
    "AUDIT": ["export"],
    "retention_days": 0,
}


class FakeRepository:
    """Stands in for SessionAuditRepository - one page, no real OpenSearch."""

    def __init__(self, events=None):
        self._events = events or []

    async def query(self, compiled_query, cursor=None, size=200):
        return self._events, None


def _make_event(session_id: int = 1, org_id: int = 7) -> SessionAuditEvent:
    return SessionAuditEvent(
        id="evt-1",
        session_id=session_id,
        kind="event",
        event_time=datetime.now(timezone.utc),
        org_id=org_id,
    )


def _build_app(events=None) -> FastAPI:
    app = FastAPI()
    app.include_router(build_export_router(SESSIONS))
    app.state.repositories = {SESSIONS.name: FakeRepository(events)}
    app.state.export_job_service = ExportJobService(
        FakeAsyncRedis(decode_responses=True)
    )
    app.dependency_overrides[verify_user_jwt] = lambda: dict(DEFAULT_CLAIMS)
    return app


@pytest_asyncio.fixture
async def app_and_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))
    app = _build_app(events=[_make_event()])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client


@pytest_asyncio.fixture
async def empty_app_and_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))
    app = _build_app(events=[])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client


@pytest.mark.asyncio
async def test_export_empty_result_set_json_is_empty_array(empty_app_and_client):
    # A filter matching nothing must still produce a valid, parseable JSON
    # document - not a truncated "[" from a scan that opened the file but
    # never wrote a row.
    app, client = empty_app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    resp = await client.get(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 200
    assert resp.content == b"[]"
    assert json.loads(resp.content) == []


@pytest.mark.asyncio
async def test_export_empty_result_set_csv_has_header_only(empty_app_and_client):
    # An empty CSV export is deliberately not a zero-byte file: the header
    # row (from the domain event model's fields) is always written before
    # the scan runs, so the columns are still visible even with no matches.
    app, client = empty_app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "csv"})
    job_id = resp.json()["job_id"]

    resp = await client.get(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 200
    lines = resp.content.decode().splitlines()
    assert lines == [",".join(SessionAuditEvent.model_fields.keys())]


@pytest.mark.asyncio
async def test_start_export_then_download_completed_job(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    resp = await client.get(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert len(body) == 1
    assert body[0]["session_id"] == 1


@pytest.mark.asyncio
async def test_start_export_writes_file_under_export_data_dir(app_and_client, tmp_path):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "csv"})
    job_id = resp.json()["job_id"]

    job = await app.state.export_job_service.get_job(job_id)
    assert job["status"] == "completed"
    file_path = pathlib.Path(job["file_path"])
    assert file_path.parent == tmp_path
    assert file_path.exists()
    assert file_path.suffix == ".csv"


@pytest.mark.asyncio
async def test_download_rejects_non_owner(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "user_id": 999,
    }
    resp = await client.get(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_rejects_wrong_org(app_and_client):
    # Same user_id, different org_id - a user who lost AUDIT:export in the
    # job's org shouldn't be able to reach it via a token minted for a
    # different org they also belong to.
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "org_id": 999,
    }
    resp = await client.get(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_returns_410_when_file_missing_after_completion(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    job = await app.state.export_job_service.get_job(job_id)
    pathlib.Path(job["file_path"]).unlink()  # simulate the manager's sweep

    resp = await client.get(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_download_unknown_job_is_404(app_and_client):
    _, client = app_and_client
    resp = await client.get("/api/audit/sessions/export/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_export_removes_file_and_job(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    job = await app.state.export_job_service.get_job(job_id)
    file_path = pathlib.Path(job["file_path"])
    assert file_path.exists()

    resp = await client.delete(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 204
    assert not file_path.exists()
    assert await app.state.export_job_service.get_job(job_id) is None


@pytest.mark.asyncio
async def test_delete_rejects_non_owner(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "user_id": 999,
    }
    resp = await client.delete(f"/api/audit/sessions/export/{job_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_missing_action_claim_is_403(app_and_client):
    app, client = app_and_client
    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "AUDIT": ["read"],
    }
    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_conflicting_filters_and_query_is_rejected(app_and_client):
    _, client = app_and_client
    resp = await client.post(
        "/api/audit/sessions/export",
        json={
            "format": "json",
            "filters": {"field": "status", "op": "equals", "value": "failed"},
            "query": "status=failed",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_get_jobs_returns_only_the_callers_jobs(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    own_job_id = resp.json()["job_id"]

    # A job owned by a different org/user combo must never leak into the
    # caller's listing.
    await app.state.export_job_service.create_job(
        domain=SESSIONS.name,
        job_id="other-job",
        org_id=999,
        user_id=999,
        ttl_seconds=3600,
        format="json",
    )

    resp = await client.get("/api/audit/sessions/export")
    assert resp.status_code == 200
    body = resp.json()
    assert [job["job_id"] for job in body] == [own_job_id]


@pytest.mark.asyncio
async def test_get_jobs_returns_empty_list_when_caller_has_no_jobs(app_and_client):
    _, client = app_and_client

    resp = await client.get("/api/audit/sessions/export")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_jobs_missing_action_claim_is_403(app_and_client):
    app, client = app_and_client
    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "AUDIT": ["read"],
    }
    resp = await client.get("/api/audit/sessions/export")
    assert resp.status_code == 403


# --- match_scope / filter_matched (ExportRequest no longer has `detail`) ---


def _tree_events(org_id: int = 7) -> list[SessionAuditEvent]:
    now = datetime.now(timezone.utc)
    return [
        SessionAuditEvent(
            id="sess-1",
            parent_id="",
            session_id=100,
            kind="session",
            status="failed",
            event_time=now,
            org_id=org_id,
        ),
        SessionAuditEvent(
            id="node-1",
            parent_id="sess-1",
            session_id=100,
            kind="node",
            status="failed",
            event_time=now + timedelta(seconds=1),
            org_id=org_id,
        ),
        SessionAuditEvent(
            id="evt-1",
            parent_id="node-1",
            session_id=100,
            kind="event",
            status="failed",
            event_time=now + timedelta(seconds=2),
            org_id=org_id,
        ),
    ]


def _build_match_scope_app(events: list[SessionAuditEvent]) -> FastAPI:
    app = FastAPI()
    app.include_router(build_export_router(SESSIONS))
    app.state.repositories = {SESSIONS.name: InMemoryFakeRepository(events)}
    app.state.export_job_service = ExportJobService(
        FakeAsyncRedis(decode_responses=True)
    )
    app.dependency_overrides[verify_user_jwt] = lambda: dict(DEFAULT_CLAIMS)
    return app


@pytest_asyncio.fixture
async def match_scope_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))

    async def _make(events: list[SessionAuditEvent]):
        app = _build_match_scope_app(events)
        transport = ASGITransport(app=app)
        return app, AsyncClient(transport=transport, base_url="http://test")

    return _make


@pytest.mark.asyncio
async def test_export_legacy_detail_field_is_silently_ignored_not_rejected(
    app_and_client,
):
    # `detail` was removed in favor of `match_scope`. `ExportRequest` has no
    # `extra="forbid"`, so a client still sending the old `{"detail": "full"}`
    # shape isn't validated against - it's just inert now (falls back to the
    # match_scope default, i.e. old "base" behavior). This documents that
    # behavior rather than asserting a 422 that would never actually happen.
    _, client = app_and_client
    resp = await client.post(
        "/api/audit/sessions/export", json={"format": "json", "detail": "full"}
    )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_export_full_session_history_uses_expand_matches_and_sets_filter_matched(
    match_scope_client,
):
    # The old implementation did its own per-session N+1 loop keyed on
    # `detail == "full"`; this now goes through the same expand_matches
    # machinery as search, keyed on match_scope.full_session_history.
    app, client = await match_scope_client(_tree_events())
    async with client:
        resp = await client.post(
            "/api/audit/sessions/export",
            json={
                "filters": {"field": "id", "op": "equals", "value": "evt-1"},
                "match_scope": {"full_session_history": True},
            },
        )
        job_id = resp.json()["job_id"]

        resp = await client.get(f"/api/audit/sessions/export/{job_id}")
        body = json.loads(resp.content)

    by_id = {row["id"]: row["filter_matched"] for row in body}
    assert by_id == {"sess-1": False, "node-1": False, "evt-1": True}


@pytest.mark.asyncio
async def test_export_no_match_scope_all_rows_filter_matched(match_scope_client):
    app, client = await match_scope_client(_tree_events())
    async with client:
        resp = await client.post(
            "/api/audit/sessions/export",
            json={"filters": {"field": "session_id", "op": "equals", "value": 100}},
        )
        job_id = resp.json()["job_id"]

        resp = await client.get(f"/api/audit/sessions/export/{job_id}")
        body = json.loads(resp.content)

    assert {row["id"] for row in body} == {"sess-1", "node-1", "evt-1"}
    assert all(row["filter_matched"] is True for row in body)


# --- multi-page scan / truncation / cross-page expansion dedup ---


def _flat_events(n: int, org_id: int = 7) -> list[SessionAuditEvent]:
    now = datetime.now(timezone.utc)
    return [
        SessionAuditEvent(
            id=f"evt-{i}",
            session_id=i,
            kind="event",
            event_time=now + timedelta(seconds=i),
            org_id=org_id,
        )
        for i in range(n)
    ]


def _session_tree(session_id: int, org_id: int = 7) -> list[SessionAuditEvent]:
    now = datetime.now(timezone.utc)
    return [
        SessionAuditEvent(
            id=f"sess-{session_id}",
            parent_id="",
            session_id=session_id,
            kind="session",
            status="failed",
            event_time=now,
            org_id=org_id,
        ),
        SessionAuditEvent(
            id=f"node-{session_id}",
            parent_id=f"sess-{session_id}",
            session_id=session_id,
            kind="node",
            status="failed",
            event_time=now + timedelta(seconds=1),
            org_id=org_id,
        ),
        SessionAuditEvent(
            id=f"evt-{session_id}-a",
            parent_id=f"node-{session_id}",
            session_id=session_id,
            kind="event",
            status="failed",
            event_time=now + timedelta(seconds=2),
            org_id=org_id,
        ),
        SessionAuditEvent(
            id=f"evt-{session_id}-b",
            parent_id=f"node-{session_id}",
            session_id=session_id,
            kind="event",
            status="failed",
            event_time=now + timedelta(seconds=3),
            org_id=org_id,
        ),
    ]


@pytest.mark.asyncio
async def test_export_scans_multiple_pages_without_duplicates_or_drops(
    match_scope_client, monkeypatch
):
    # SCAN_PAGE_SIZE is looked up fresh from app.services.search_pipeline's
    # module globals on every _scan_all call, so patching the module
    # attribute (not a local import) actually takes effect here. Every
    # fake repository used elsewhere in this suite returns everything in
    # one page (small event counts vs. the real SCAN_PAGE_SIZE=200), which
    # is exactly why this bug class (see the expansion test below) went
    # uncaught - shrinking the page size is what forces >1 page.
    monkeypatch.setattr(search_pipeline, "SCAN_PAGE_SIZE", 2)
    events = _flat_events(5)
    app, client = await match_scope_client(events)
    async with client:
        resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
        job_id = resp.json()["job_id"]

        resp = await client.get(f"/api/audit/sessions/export/{job_id}")
        body = json.loads(resp.content)

    # 5 rows over a page size of 2 forces 3 scan pages (2, 2, 1) - confirms
    # SearchPipeline.scan/the export write path actually iterates every
    # page rather than stopping after the first, with no row dropped and
    # none written twice.
    assert {row["id"] for row in body} == {f"evt-{i}" for i in range(5)}
    assert len(body) == 5


@pytest.mark.asyncio
async def test_export_truncates_at_max_rows_and_marks_job_truncated(
    match_scope_client, monkeypatch
):
    monkeypatch.setattr(search_pipeline, "SCAN_PAGE_SIZE", 2)
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_MAX_ROWS", 3)
    events = _flat_events(5)
    app, client = await match_scope_client(events)
    async with client:
        resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
        job_id = resp.json()["job_id"]

        # The job must be marked truncated (not just the file capped) so
        # the caller knows the export stopped early rather than covering
        # every matching row.
        job = await app.state.export_job_service.get_job(job_id)
        assert job["truncated"] == "True"

        resp = await client.get(f"/api/audit/sessions/export/{job_id}")
        body = json.loads(resp.content)

    # Exactly the capped row count was written, not the 4 rows two 2-row
    # pages would produce before the cap stopped the scan mid-page-3.
    assert len(body) == 3


@pytest.mark.asyncio
async def test_export_multi_page_full_session_history_dedupes_across_pages(
    match_scope_client, monkeypatch
):
    # Regression coverage for the `yield await expand_and_mark(...)`
    # coroutine bug in SearchPipeline.scan: it only ever manifests once a
    # match-scope expansion runs across more than one scan page - every
    # prior full_session_history test in this file uses a single page and
    # would pass even with that bug present.
    monkeypatch.setattr(search_pipeline, "SCAN_PAGE_SIZE", 1)
    events = _session_tree(100)
    app, client = await match_scope_client(events)
    async with client:
        resp = await client.post(
            "/api/audit/sessions/export",
            json={
                "filters": {"field": "kind", "op": "equals", "value": "event"},
                "match_scope": {"full_session_history": True},
            },
        )
        job_id = resp.json()["job_id"]

        resp = await client.get(f"/api/audit/sessions/export/{job_id}")
        body = json.loads(resp.content)

    # The 2 matched events (evt-100-a, evt-100-b) land on 2 separate scan
    # pages (page size 1); each page independently expands to the *same*
    # full 4-row session tree. Without ExportWriteService's seen_ids dedup
    # across pages, the file would contain 8 rows instead of these 4.
    assert {row["id"] for row in body} == {
        "sess-100",
        "node-100",
        "evt-100-a",
        "evt-100-b",
    }
    assert len(body) == 4


@pytest.mark.asyncio
async def test_get_jobs_never_exposes_file_path_or_internal_fields(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/sessions/export", json={"format": "csv"})
    job_id = resp.json()["job_id"]
    stored_job = await app.state.export_job_service.get_job(job_id)
    assert stored_job["file_path"]

    resp = await client.get("/api/audit/sessions/export")

    assert resp.status_code == 200
    (listed_job,) = resp.json()
    assert set(listed_job) == {
        "job_id",
        "status",
        "format",
        "created_at",
        "expires_at",
        "truncated",
    }
    assert listed_job["job_id"] == job_id
    assert listed_job["status"] == "completed"
    assert listed_job["format"] == "csv"
    assert listed_job["truncated"] is False
    assert stored_job["file_path"] not in resp.text


@pytest.mark.asyncio
async def test_failed_export_stores_no_exception_text(app_and_client, monkeypatch):
    app, client = app_and_client

    class ExplodingRepository:
        async def query(self, compiled_query, cursor=None, size=200):
            raise RuntimeError("secret internal detail /srv/path")

    app.state.repositories = {SESSIONS.name: ExplodingRepository()}

    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    stored_job = await app.state.export_job_service.get_job(job_id)
    assert stored_job["status"] == "failed"
    assert "secret internal detail" not in json.dumps(stored_job)

    resp = await client.get("/api/audit/sessions/export")
    assert "secret internal detail" not in resp.text
    assert resp.json()[0]["status"] == "failed"


def _formula_event(name: str, details: dict | None = None) -> SessionAuditEvent:
    return SessionAuditEvent(
        id=f"evt-{abs(hash(name))}",
        session_id=1,
        kind="event",
        name=name,
        details=details or {},
        event_time=datetime.now(timezone.utc),
        org_id=7,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "malicious_value",
    ["=HYPERLINK(\"http://evil\")", "+1+1", "-2+3", "@SUM(A1)", "\t=1", "\r=1"],
)
async def test_csv_export_neutralizes_formula_leading_cells(
    tmp_path, monkeypatch, malicious_value
):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))
    app = _build_app(events=[_formula_event(malicious_value)])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/audit/sessions/export", json={"format": "csv"})
        job_id = resp.json()["job_id"]
        resp = await client.get(f"/api/audit/sessions/export/{job_id}")

    (row,) = list(csv.DictReader(io.StringIO(resp.content.decode(), newline="")))
    assert row["name"] == f"'{malicious_value}"


@pytest.mark.asyncio
async def test_csv_export_leaves_ordinary_cells_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))
    app = _build_app(events=[_formula_event("Session Start", {"answer": "=42"})])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/audit/sessions/export", json={"format": "csv"})
        job_id = resp.json()["job_id"]
        resp = await client.get(f"/api/audit/sessions/export/{job_id}")

    (row,) = list(csv.DictReader(io.StringIO(resp.content.decode(), newline="")))
    assert row["name"] == "Session Start"
    # A JSON blob starts with "{" and is not a formula, even if a nested value is.
    assert json.loads(row["details"]) == {"answer": "=42"}


@pytest.mark.asyncio
async def test_json_export_is_not_formula_escaped(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))
    app = _build_app(events=[_formula_event("=1+1")])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
        job_id = resp.json()["job_id"]
        resp = await client.get(f"/api/audit/sessions/export/{job_id}")

    assert json.loads(resp.content)[0]["name"] == "=1+1"


@pytest.mark.asyncio
async def test_export_rejects_token_granting_export_on_another_resource_only(
    app_and_client,
):
    app, client = app_and_client
    app.dependency_overrides[verify_user_jwt] = lambda: {
        "org_id": 7,
        "user_id": 42,
        "retention_days": 0,
        "BILLING": ["export"],
    }
    resp = await client.post("/api/audit/sessions/export", json={"format": "json"})
    assert resp.status_code == 403
