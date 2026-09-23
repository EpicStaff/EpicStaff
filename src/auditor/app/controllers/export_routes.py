import os
import io
import csv
import json
import pathlib
import uuid
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from loguru import logger
from pydantic import BaseModel

from app.core.security import require_audit_action
from app.core import settings
from app.domains.base import AuditDomain
from app.repositories.base import AuditRepository
from app.repositories.compiler import QueryCompiler
from app.services.export_job_service import ExportJobService, JobStatus
from app.services.search_pipeline import SearchPipeline


async def _get_owned_job(
    job_service: ExportJobService, job_id: str, claims: dict
) -> dict:
    """Fetch a job and enforce ownership. 404 either way (missing, not yours,
    or not your org) so a non-owner can't distinguish the cases. Org is
    checked alongside user_id, not instead of it: a user in multiple orgs
    could otherwise lose AUDIT:export in org A and still reach an org-A job
    via a token minted for org B."""
    job = await job_service.get_job(job_id)
    if (
        job is None
        or str(job.get("user_id")) != str(claims["user_id"])
        or str(job.get("org_id")) != str(claims["org_id"])
    ):
        raise HTTPException(404, "Export job not found")
    return job


def _to_csv(rows: list[dict], event_model: type[BaseModel]) -> bytes:
    # Columns come from the domain's own event model, not from rows[0]: an
    # empty result set used to produce a zero-byte file with no header row
    # at all, which reads as a broken download rather than "no matching
    # events".
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(event_model.model_fields))
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                for k, v in row.items()
            }
        )
    return output.getvalue().encode()


async def _write_export_output(
    job_id: str,
    events: list,
    format: Literal["json", "csv"],
    job_service: ExportJobService,
    event_model: type[BaseModel],
) -> None:
    rows = [e.model_dump(mode="json") for e in events]
    content = (
        _to_csv(rows, event_model) if format == "csv" else json.dumps(rows).encode()
    )

    os.makedirs(settings.AUDITOR_EXPORT_DATA_DIR, exist_ok=True)
    file_path = os.path.join(settings.AUDITOR_EXPORT_DATA_DIR, f"{job_id}.{format}")

    with open(file_path, "wb") as f:
        f.write(content)

    was_recorded = await job_service.mark_done(job_id, file_path)

    if not was_recorded:
        pathlib.Path(file_path).unlink(missing_ok=True)


def build_export_router(domain: AuditDomain) -> APIRouter:
    """Mounts one domain's export endpoints, namespaced under
    `/api/audit/{domain.name}/export...` - same reasoning as
    build_search_router's `/api/audit/{domain.name}/search`. Without this
    prefix, a second domain's export router would build the exact same
    unparameterized `/api/audit/export` path as the first-registered
    domain, so FastAPI would route every export request to whichever
    domain mounted first regardless of which domain the caller meant, and
    the second domain's export endpoints would be permanently unreachable.

    Domain-generic: the request model type comes off `domain` (see
    app/domains/base.py::ApiSpec.export_request_model) rather than a
    hardcoded sessions-specific class."""
    router = APIRouter(tags=["Export"])
    pipeline = SearchPipeline(
        catalog=domain.fields,
        compiler=QueryCompiler(catalog=domain.fields, scoping=domain.scoping),
        computed=domain.computed,
        expander=domain.expander,
        event_model=domain.event_model,
    )
    ExportRequest = domain.api.export_request_model

    async def _run_export(
        job_id: str,
        body: ExportRequest,
        claims: dict,
        repository: AuditRepository,
        job_service: ExportJobService,
    ) -> None:
        try:
            org_id = claims["org_id"]
            retention_days = claims["retention_days"]

            filter_node = body.resolve_filter_node()
            events = await pipeline.scan(
                repository,
                filter_node,
                body.match_scope,
                org_id=org_id,
                retention_days=retention_days,
            )

            await _write_export_output(
                job_id, events, body.format, job_service, pipeline.event_model
            )

        except Exception as e:
            logger.exception(f"Export job {job_id} failed: {e}")
            await job_service.mark_failed(job_id, str(e)[:500])

    @router.post(f"/api/audit/{domain.name}/export")
    async def start_export(
        body: ExportRequest,
        background_tasks: BackgroundTasks,
        request: Request,
        claims: dict = Depends(require_audit_action(domain, "export")),
    ):
        repository = request.app.state.repositories[domain.name]
        job_service = request.app.state.export_job_service
        job_id = str(uuid.uuid4())

        await job_service.create_job(
            job_id=job_id,
            org_id=claims["org_id"],
            user_id=claims["user_id"],
            ttl_seconds=settings.AUDITOR_EXPORT_FILE_TTL_SECONDS,
            format=body.format,
        )

        background_tasks.add_task(
            _run_export,
            job_id,
            body,
            claims,
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
        job = await _get_owned_job(job_service, job_id, claims)
        if job["status"] == JobStatus.FAILED.value:
            raise HTTPException(status_code=500, detail="Export job failed")
        if job["status"] != JobStatus.COMPLETED.value:
            return {"status": job["status"]}

        path = pathlib.Path(job["file_path"])
        if not path.exists():
            raise HTTPException(status_code=410, detail="Export file has expired")
        ext = path.suffix.lstrip(".")
        media_type = "text/csv" if ext == "csv" else "application/json"

        return FileResponse(
            path, media_type=media_type, filename=f"audit-export-{job_id}.{ext}"
        )

    @router.get(f"/api/audit/{domain.name}/export")
    async def get_jobs(
        request: Request, claims: dict = Depends(require_audit_action(domain, "export"))
    ):
        job_service = request.app.state.export_job_service
        jobs = await job_service.get_jobs_by_user(claims["org_id"], claims["user_id"])

        return list(jobs)

    @router.delete(f"/api/audit/{domain.name}/export/{{job_id}}")
    async def delete_export(
        job_id: str,
        request: Request,
        claims: dict = Depends(require_audit_action(domain, "export")),
    ):
        job_service = request.app.state.export_job_service
        job = await _get_owned_job(job_service, job_id, claims)

        if job.get("file_path"):
            pathlib.Path(job["file_path"]).unlink(missing_ok=True)

        await job_service.delete_job(job_id, claims["org_id"], claims["user_id"])
        return Response(status_code=204)

    return router
