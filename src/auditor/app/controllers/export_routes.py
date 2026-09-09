import os
import io
import csv
import json
import pathlib
import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from loguru import logger
from pydantic import BaseModel, model_validator

from src.shared.models import SessionAuditEvent
from app.core.security import require_audit_action
from app.core.settings import settings
from app.repositories.base import SessionAuditRepository
from app.repositories.opensearch_query_compiler import compile as compile_filters
from app.filtering.ast import FilterNode, validate_filter_node
from app.filtering.query_language import parse_query
from app.services.export_job_service import ExportJobService, JobStatus

router = APIRouter(tags=["Export"])


class ExportRequest(BaseModel):
    format: Literal["json", "csv"] = "json"
    detail: Literal["base", "full"] = "base"
    filters: dict | None = None
    query: str | None = None

    @model_validator(mode="after")
    def _filters_xor_query(self):
        if self.filters is not None and self.query is not None:
            raise ValueError(
                "'filters' and 'query' are mutually exclusive - send exactly one"
            )
        return self

    def resolve_filter_node(self) -> FilterNode | None:
        if self.filters is not None:
            return self.filters
        if self.query:
            return parse_query(self.query)
        return None


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


@router.post("/api/audit/export")
async def start_export(
    body: ExportRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    claims: dict = Depends(require_audit_action("export")),
):
    repository = request.app.state.session_audit_repository
    job_service = request.app.state.export_job_service
    job_id = str(uuid.uuid4())

    await job_service.create_job(
        job_id=job_id,
        org_id=claims["org_id"],
        user_id=claims["user_id"],
        ttl_seconds=settings.EXPORT_FILE_TTL_SECONDS,
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


@router.get("/api/audit/export/{job_id}")
async def get_export(
    job_id: str,
    request: Request,
    claims: dict = Depends(require_audit_action("export")),
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


@router.get("/api/audit/export")
async def get_jobs(
    request: Request, claims: dict = Depends(require_audit_action("export"))
):
    job_service = request.app.state.export_job_service
    jobs = await job_service.get_jobs_by_user(claims["org_id"], claims["user_id"])

    return list(jobs)


@router.delete("/api/audit/export/{job_id}")
async def delete_export(
    job_id: str,
    request: Request,
    claims: dict = Depends(require_audit_action("export")),
):
    job_service = request.app.state.export_job_service
    job = await _get_owned_job(job_service, job_id, claims)

    if job.get("file_path"):
        pathlib.Path(job["file_path"]).unlink(missing_ok=True)

    await job_service.delete_job(job_id, claims["org_id"], claims["user_id"])
    return Response(status_code=204)


async def _run_export(
    job_id: str,
    body: ExportRequest,
    claims: dict,
    repository: SessionAuditRepository,
    job_service: ExportJobService,
) -> None:
    try:
        org_id = claims["org_id"]
        retention_days = claims.get("retention_days", 0)

        filter_node = body.resolve_filter_node()
        if filter_node is not None:
            validate_filter_node(filter_node)
        compiled = compile_filters(
            filter_node, org_id=org_id, retention_days=retention_days
        )

        events = await _collect_all(repository, compiled)

        if body.detail == "full":
            expanded = []
            seen_sessions: set[int] = set()
            for matched in events:
                if matched.session_id in seen_sessions:
                    continue
                seen_sessions.add(matched.session_id)
                session_query = compile_filters(
                    None,
                    org_id=org_id,
                    retention_days=retention_days,
                    extra_filters=[{"term": {"session_id": matched.session_id}}],
                )
                tree = await _collect_all(repository, session_query)
                expanded.extend(tree)
            events = expanded

        rows = [e.model_dump(mode="json") for e in events]
        ext = "csv" if body.format == "csv" else "json"
        content = _to_csv(rows) if ext == "csv" else json.dumps(rows).encode()

        os.makedirs(settings.EXPORT_DATA_DIR, exist_ok=True)
        file_path = os.path.join(settings.EXPORT_DATA_DIR, f"{job_id}.{ext}")

        with open(file_path, "wb") as f:
            f.write(content)

        was_recorded = await job_service.mark_done(job_id, file_path)
        if not was_recorded:
            pathlib.Path(file_path).unlink(missing_ok=True)

    except Exception as e:
        logger.exception(f"Export job {job_id} failed: {e}")
        await job_service.mark_failed(job_id, str(e)[:500])


async def _collect_all(
    repository: SessionAuditRepository, compiled_query: dict
) -> list:
    events = []
    cursor = None
    while True:
        page, cursor = await repository.query(compiled_query, cursor=cursor, size=200)
        events.extend(page)
        if cursor is None or not page:
            break
    return events


def _to_csv(rows: list[dict]) -> bytes:
    # Columns come from the model, not from rows[0]: an empty result set used
    # to produce a zero-byte file with no header row at all, which reads as a
    # broken download rather than "no matching events".
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(SessionAuditEvent.model_fields))
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                k: (json.dumps(v) if isinstance(v, (dict, list)) else v)
                for k, v in row.items()
            }
        )
    return output.getvalue().encode()
