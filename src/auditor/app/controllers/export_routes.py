import pathlib
import uuid

from app.core import settings
from app.core.security import require_audit_action
from app.domains.base import AuditDomain
from app.services.export_job_service import ExportJobService, JobStatus
from app.services.export_write_service import ExportWriteService
from app.services.search_pipeline import SearchPipeline
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel


class ExportJobSummary(BaseModel):
    """Public projection of a stored export job - never exposes the server-side
    file path or failure internals."""

    job_id: str
    status: JobStatus
    format: str
    created_at: float
    expires_at: float
    truncated: bool = False


def _resolve_export_file_path(job_id: str, fmt: str) -> pathlib.Path:
    """Rebuilds the export file's path from the job id and format instead of
    trusting the `file_path` stored in Redis: that hash is writable by
    anything on sandbox-network, so a forged `file_path` (e.g.
    `/proc/self/environ`, or a path outside the export directory) must
    never reach `FileResponse`/`unlink()` regardless of what the hash says.
    """
    if fmt not in ("csv", "json"):
        raise HTTPException(404, "Export job not found")

    export_dir = pathlib.Path(settings.AUDITOR_EXPORT_DATA_DIR).resolve()
    path = (export_dir / f"{job_id}.{fmt}").resolve()
    if not path.is_relative_to(export_dir):
        raise HTTPException(404, "Export job not found")
    return path


async def _get_owned_job(
    job_service: ExportJobService, job_id: str, claims: dict, domain_name: str
) -> dict:
    """Fetch a job and enforce ownership. 404 either way (missing, not yours,
    not your org, or not this domain's) so a non-owner can't distinguish the
    cases. Org is checked alongside user_id, not instead of it: a user in
    multiple orgs could otherwise lose AUDIT:export in org A and still reach
    an org-A job via a token minted for org B. Domain is checked so a job
    created under one audit domain can't be downloaded/deleted through
    another domain's export routes even if a job_id ever collided."""
    job = await job_service.get_job(job_id)
    if (
        job is None
        or str(job.get("user_id")) != str(claims["user_id"])
        or str(job.get("org_id")) != str(claims["org_id"])
        or job.get("domain") != domain_name
    ):
        raise HTTPException(404, "Export job not found")
    return job


def build_export_router(domain: AuditDomain) -> APIRouter:
    """Mounts `domain`'s export endpoints under `/api/audit/{domain.name}/export`."""
    router = APIRouter(tags=["Export"])
    pipeline = SearchPipeline.from_domain(domain)
    export_request_model = domain.api.export_request_model

    @router.post(f"/api/audit/{domain.name}/export")
    async def start_export(
        body: export_request_model,
        background_tasks: BackgroundTasks,
        request: Request,
        claims: dict = Depends(require_audit_action(domain, "export")),
    ):
        repository = request.app.state.repositories[domain.name]
        job_service = request.app.state.export_job_service
        job_id = str(uuid.uuid4())

        await job_service.create_job(
            domain=domain.name,
            job_id=job_id,
            org_id=claims["org_id"],
            user_id=claims["user_id"],
            ttl_seconds=settings.AUDITOR_EXPORT_FILE_TTL_SECONDS,
            format=body.format,
        )

        background_tasks.add_task(
            ExportWriteService.run_export,
            job_id,
            body,
            claims,
            pipeline,
            repository,
            job_service,
        )
        return {"job_id": job_id}

    @router.get(f"/api/audit/{domain.name}/export/{{job_id}}")
    async def get_export(
        job_id: str,
        request: Request,
        claims: dict = Depends(require_audit_action(domain, "export")),
    ):
        job_service = request.app.state.export_job_service
        job = await _get_owned_job(job_service, job_id, claims, domain.name)
        if job["status"] == JobStatus.FAILED.value:
            raise HTTPException(status_code=500, detail="Export job failed")
        if job["status"] != JobStatus.COMPLETED.value:
            return {"status": job["status"]}

        path = _resolve_export_file_path(job_id, job["format"])
        if not path.exists():
            raise HTTPException(status_code=410, detail="Export file has expired")
        ext = path.suffix.lstrip(".")
        media_type = "text/csv" if ext == "csv" else "application/json"

        return FileResponse(path, media_type=media_type, filename=f"audit-export-{job_id}.{ext}")

    @router.get(f"/api/audit/{domain.name}/export")
    async def get_jobs(
        request: Request, claims: dict = Depends(require_audit_action(domain, "export"))
    ) -> list[ExportJobSummary]:
        job_service = request.app.state.export_job_service
        jobs = await job_service.get_jobs_by_user(domain.name, claims["org_id"], claims["user_id"])
        return [ExportJobSummary.model_validate(job) for job in jobs]

    @router.delete(f"/api/audit/{domain.name}/export/{{job_id}}")
    async def delete_export(
        job_id: str,
        request: Request,
        claims: dict = Depends(require_audit_action(domain, "export")),
    ):
        job_service = request.app.state.export_job_service
        job = await _get_owned_job(job_service, job_id, claims, domain.name)

        if job.get("file_path"):
            _resolve_export_file_path(job_id, job["format"]).unlink(missing_ok=True)

        await job_service.delete_job(job_id, claims["org_id"], claims["user_id"], domain.name)
        return Response(status_code=204)

    return router
