import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from fakeredis import FakeAsyncRedis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.controllers.export_routes import build_export_router
from app.core import settings
from app.domains.sessions.domain import SESSIONS
from app.services.export_job_service import ExportJobService
from src.shared.audit.export_jobs import JOB_KEY_PREFIX
from src.shared.models import SessionAuditEvent
from tests._auth import auth
from tests._fakes import InMemoryFakeRepository

pytestmark = pytest.mark.asyncio

EXPORT_PATH = "/api/audit/sessions/export"
NOW = datetime.now(timezone.utc)


def _event(event_id: str = "evt-1", *, org_id: int = 7, seconds: int = 0, **fields):
    return SessionAuditEvent(
        **{
            "id": event_id,
            "session_id": 1,
            "kind": "event",
            "event_time": NOW + timedelta(seconds=seconds),
            "org_id": org_id,
            **fields,
        }
    )


class ExportService:
    """The export routes over an in-memory repository, a fake Redis and a temp export dir."""

    def __init__(self, app: FastAPI, client: AsyncClient, export_dir, redis_client):
        self.app = app
        self.redis_client = redis_client
        self.client = client
        self.export_dir = export_dir

    @property
    def jobs(self) -> ExportJobService:
        return self.app.state.export_job_service

    def store(self, events: list[SessionAuditEvent]) -> None:
        self.app.state.repositories = {SESSIONS.name: InMemoryFakeRepository(events)}

    async def export(self, body: dict | None = None) -> str:
        response = await self.client.post(EXPORT_PATH, json={"format": "json", **(body or {})})
        assert response.status_code == 200
        return response.json()["job_id"]

    async def download(self, job_id: str):
        return await self.client.get(f"{EXPORT_PATH}/{job_id}")


@pytest_asyncio.fixture
async def service(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "AUDITOR_EXPORT_DATA_DIR", str(tmp_path))
    app = FastAPI()
    app.include_router(build_export_router(SESSIONS))
    app.state.repositories = {SESSIONS.name: InMemoryFakeRepository([_event()])}
    redis_client = FakeAsyncRedis(decode_responses=True)
    app.state.export_job_service = ExportJobService(redis_client)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test", headers=auth()) as client:
        yield ExportService(app, client, tmp_path, redis_client)


async def test_export_is_written_to_the_export_dir_and_downloadable(service):
    service.store([_event("evt-1"), _event("evt-other-org", org_id=999)])

    job_id = await service.export()
    response = await service.download(job_id)

    assert response.status_code == 200
    assert [row["id"] for row in json.loads(response.content)] == ["evt-1"]
    # The manager's cleanup sweep looks for the file under this exact name.
    assert (service.export_dir / f"{job_id}.json").exists()


async def test_download_of_a_pending_job_returns_202(service):
    await service.jobs.create_job(
        domain="sessions", job_id="job-pending", org_id=7, user_id=42,
        ttl_seconds=3600, format="json",
    )

    response = await service.download("job-pending")

    assert response.status_code == 202
    assert response.json() == {"status": "pending"}


@pytest.mark.parametrize(
    ("method", "caller"),
    [
        ("GET", {"user_id": 999}),
        # A user who lost export rights in the job's org must not reach it through
        # a token minted for another org they belong to.
        ("GET", {"org_id": 999}),
        ("DELETE", {"user_id": 999}),
    ],
    ids=["download-by-another-user", "download-from-another-org", "delete-by-another-user"],
)
async def test_another_callers_job_looks_like_it_does_not_exist(service, method, caller):
    job_id = await service.export()

    response = await service.client.request(
        method, f"{EXPORT_PATH}/{job_id}", headers=auth(**caller)
    )

    assert response.status_code == 404
    assert (service.export_dir / f"{job_id}.json").exists()


async def test_unknown_job_is_404(service):
    assert (await service.download("does-not-exist")).status_code == 404


async def test_download_returns_410_once_the_file_was_swept(service):
    job_id = await service.export()
    (service.export_dir / f"{job_id}.json").unlink()

    response = await service.download(job_id)

    assert response.status_code == 410


@pytest.mark.parametrize("method", ["GET", "DELETE"])
async def test_forged_file_path_in_redis_is_never_served_or_deleted(service, tmp_path, method):
    """Redis is reachable from the sandbox network, so the stored file_path is never
    trusted: the routes rebuild the path from the job id and format."""
    job_id = await service.export()
    secret_file = tmp_path.parent / "secret.txt"
    secret_file.write_text("do-not-touch")
    await service.redis_client.hset(f"{JOB_KEY_PREFIX}{job_id}", "file_path", str(secret_file))

    response = await service.client.request(method, f"{EXPORT_PATH}/{job_id}")

    assert response.status_code in (200, 204)
    assert b"do-not-touch" not in response.content
    assert secret_file.read_text() == "do-not-touch"


async def test_delete_removes_the_file_and_the_job(service):
    job_id = await service.export()

    response = await service.client.delete(f"{EXPORT_PATH}/{job_id}")

    assert response.status_code == 204
    assert not (service.export_dir / f"{job_id}.json").exists()
    assert (await service.download(job_id)).status_code == 404


async def test_conflicting_filters_and_query_is_rejected(service):
    response = await service.client.post(
        EXPORT_PATH,
        json={
            "format": "json",
            "filters": {"field": "status", "op": "equals", "value": "failed"},
            "query": "status=failed",
        },
    )

    assert response.status_code == 422


async def test_job_list_shows_only_the_callers_jobs_and_no_internals(service):
    own_job_id = await service.export({"format": "csv"})
    await service.jobs.create_job(
        domain=SESSIONS.name, job_id="other-job", org_id=999, user_id=999,
        ttl_seconds=3600, format="json",
    )

    response = await service.client.get(EXPORT_PATH)

    assert response.status_code == 200
    (listed_job,) = response.json()
    assert set(listed_job) == {"job_id", "status", "format", "created_at", "expires_at", "truncated"}
    assert (listed_job["job_id"], listed_job["status"], listed_job["format"]) == (
        own_job_id, "completed", "csv",
    )
    assert listed_job["truncated"] is False
    assert str(service.export_dir) not in response.text


async def test_failed_export_is_a_500_without_the_exception_text(service):
    class ExplodingRepository:
        async def query(self, compiled_query, cursor=None, size=200):
            raise RuntimeError("secret internal detail /srv/path")

    service.app.state.repositories = {SESSIONS.name: ExplodingRepository()}

    download = await service.download(await service.export())

    assert download.status_code == 500
    assert "secret internal detail" not in download.text
    listing = await service.client.get(EXPORT_PATH)
    assert listing.json()[0]["status"] == "failed"
    assert "secret internal detail" not in listing.text
