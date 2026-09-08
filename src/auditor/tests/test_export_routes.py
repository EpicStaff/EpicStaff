import os

# Settings() requires these at import time (no defaults) - set dummy values
# before anything under app.* gets imported, so this module is runnable on
# its own without a real .env file (mirrors what docker-compose injects).
os.environ.setdefault("OPENSEARCH_PASSWORD", "test")
os.environ.setdefault("AUDITOR_INGEST_API_KEY", "test-ingest-key")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("REDIS_HOST", "localhost")
os.environ.setdefault("REDIS_PORT", "6379")
os.environ.setdefault("REDIS_PASSWORD", "")
os.environ.setdefault("AUDITOR_REDIS_DB", "1")

import json
import pathlib
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.controllers import export_routes
from app.core.security import verify_user_jwt
from app.core.settings import settings
from app.services.export_job_service import ExportJobService
from src.shared.models import SessionAuditEvent

DEFAULT_CLAIMS = {"org_id": 7, "user_id": 42, "actions": ["export"], "retention_days": 0}


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
    app.include_router(export_routes.router)
    app.state.session_audit_repository = FakeRepository(events)
    app.state.export_job_service = ExportJobService(
        FakeAsyncRedis(decode_responses=True)
    )
    app.dependency_overrides[verify_user_jwt] = lambda: dict(DEFAULT_CLAIMS)
    return app


@pytest_asyncio.fixture
async def app_and_client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "EXPORT_DATA_DIR", str(tmp_path))
    app = _build_app(events=[_make_event()])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield app, client


@pytest.mark.asyncio
async def test_start_export_then_download_completed_job(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/export", json={"format": "json"})
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    resp = await client.get(f"/api/audit/export/{job_id}")
    assert resp.status_code == 200
    body = json.loads(resp.content)
    assert len(body) == 1
    assert body[0]["session_id"] == 1


@pytest.mark.asyncio
async def test_start_export_writes_file_under_export_data_dir(app_and_client, tmp_path):
    app, client = app_and_client

    resp = await client.post("/api/audit/export", json={"format": "csv"})
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

    resp = await client.post("/api/audit/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "user_id": 999,
    }
    resp = await client.get(f"/api/audit/export/{job_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_rejects_wrong_org(app_and_client):
    # Same user_id, different org_id - a user who lost AUDIT:export in the
    # job's org shouldn't be able to reach it via a token minted for a
    # different org they also belong to.
    app, client = app_and_client

    resp = await client.post("/api/audit/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "org_id": 999,
    }
    resp = await client.get(f"/api/audit/export/{job_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_download_returns_410_when_file_missing_after_completion(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    job = await app.state.export_job_service.get_job(job_id)
    pathlib.Path(job["file_path"]).unlink()  # simulate the manager's sweep

    resp = await client.get(f"/api/audit/export/{job_id}")
    assert resp.status_code == 410


@pytest.mark.asyncio
async def test_download_unknown_job_is_404(app_and_client):
    _, client = app_and_client
    resp = await client.get("/api/audit/export/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_export_removes_file_and_job(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    job = await app.state.export_job_service.get_job(job_id)
    file_path = pathlib.Path(job["file_path"])
    assert file_path.exists()

    resp = await client.delete(f"/api/audit/export/{job_id}")
    assert resp.status_code == 204
    assert not file_path.exists()
    assert await app.state.export_job_service.get_job(job_id) is None


@pytest.mark.asyncio
async def test_delete_rejects_non_owner(app_and_client):
    app, client = app_and_client

    resp = await client.post("/api/audit/export", json={"format": "json"})
    job_id = resp.json()["job_id"]

    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "user_id": 999,
    }
    resp = await client.delete(f"/api/audit/export/{job_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_export_missing_action_claim_is_403(app_and_client):
    app, client = app_and_client
    app.dependency_overrides[verify_user_jwt] = lambda: {
        **DEFAULT_CLAIMS,
        "actions": ["read"],
    }
    resp = await client.post("/api/audit/export", json={"format": "json"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_conflicting_filters_and_query_is_rejected(app_and_client):
    _, client = app_and_client
    resp = await client.post(
        "/api/audit/export",
        json={"format": "json", "filters": {"field": "status", "op": "equals", "value": "failed"}, "query": "status=failed"},
    )
    assert resp.status_code == 422
