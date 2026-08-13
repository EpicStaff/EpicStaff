import csv
import io
import json
import uuid
from typing import Any, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import Response
from loguru import logger
from pydantic import BaseModel

from app.core.security import require_audit_action
from app.repositories.base import SessionAuditRepository
from src.shared.models import SessionAuditEvent

router = APIRouter(tags=["Export"])

# In-memory job store - fine for a single-instance MVP; a real deployment
# with multiple auditor replicas would need this in a shared store instead.
_jobs: dict[str, dict[str, Any]] = {}


class ExportRequest(BaseModel):
    format: Literal["json", "csv"] = "json"
    detail: Literal["base", "full"] = "base"  # "base" = session rows only
    session_id: int | None = None  # single-session export
    search: str | None = None  # filtered-list export (ignored if session_id set)


@router.post("/api/audit/export")
async def start_export(
    body: ExportRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    claims: dict = Depends(require_audit_action("export")),
):
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {"status": "pending"}
    background_tasks.add_task(
        _run_export, job_id, body, claims, request.app.state.session_audit_repository
    )
    return {"job_id": job_id}


@router.get("/api/audit/export/{job_id}")
async def get_export(job_id: str, claims: dict = Depends(require_audit_action("export"))):
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Export job not found")
    if job["status"] == "failed":
        raise HTTPException(status_code=500, detail="Export job failed")
    if job["status"] != "done":
        return {"status": job["status"]}

    result = job["result"]
    return Response(
        content=result["content"],
        media_type=result["media_type"],
        headers={"Content-Disposition": f'attachment; filename="{result["filename"]}"'},
    )


async def _run_export(
    job_id: str, body: ExportRequest, claims: dict, repository: SessionAuditRepository
) -> None:
    try:
        base_filters = {
            "org_id": claims["org_id"],
            "retention_days": claims.get("retention_days", 0),
        }

        if body.session_id is not None:
            events = await _collect_all(
                repository, {**base_filters, "session_id": body.session_id}
            )
        else:
            filters = {**base_filters, "kind": "session"}
            if body.search:
                filters["search"] = body.search
            events = await _collect_all(repository, filters)

            if body.detail == "full":
                expanded = []
                for session_event in events:
                    tree = await _collect_all(
                        repository,
                        {**base_filters, "session_id": session_event.session_id},
                    )
                    expanded.extend(tree)
                events = expanded

        rows = [e.model_dump(mode="json") for e in events]

        if body.format == "csv":
            content = _to_csv(rows)
            media_type, filename = "text/csv", f"audit-export-{job_id}.csv"
        else:
            content = json.dumps(rows).encode()
            media_type, filename = "application/json", f"audit-export-{job_id}.json"

        _jobs[job_id] = {
            "status": "done",
            "result": {"content": content, "media_type": media_type, "filename": filename},
        }
    except Exception as e:
        logger.exception(f"Export job {job_id} failed: {e}")
        _jobs[job_id] = {"status": "failed"}


async def _collect_all(repository: SessionAuditRepository, filters: dict) -> list:
    events = []
    cursor = None
    while True:
        page, cursor = await repository.query(filters=filters, cursor=cursor, size=200)
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
            {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in row.items()}
        )
    return output.getvalue().encode()
