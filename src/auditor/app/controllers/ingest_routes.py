from app.core.security import verify_ingest_api_key
from app.domains.base import AuditDomain
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger


def _extract_failed_ids(errors: list[dict]) -> list[str]:
    failed_ids = []
    for error in errors:
        for item in error.values():
            doc_id = item.get("_id")
            if doc_id is not None:
                failed_ids.append(doc_id)
    return failed_ids


def build_ingest_router(domain: AuditDomain) -> APIRouter:
    """Mounts `domain`'s ingest endpoint at `/api/audit/{domain.name}/events`."""
    router = APIRouter(tags=["Ingest"])
    event_model = domain.event_model

    # FastAPI resolves this closure-captured annotation at route registration,
    # so this module must not use `from __future__ import annotations`.
    async def ingest_events(events: list[event_model], request: Request):
        logger.info("Ingesting {} audit event(s) into {!r}", len(events), domain.name)
        errors = await request.app.state.repositories[domain.name].write_batch(events)

        if not errors:
            return {"received": len(events)}

        failed_ids = _extract_failed_ids(errors)
        logger.error(
            "Audit bulk write to {!r} partially failed: {}/{} event(s) not indexed - failed_ids={}",
            domain.name,
            len(failed_ids),
            len(events),
            failed_ids,
        )
        return JSONResponse(
            {"received": len(events) - len(errors), "failed_ids": failed_ids},
            status_code=207,
        )

    router.add_api_route(
        f"/api/audit/{domain.name}/events",
        ingest_events,
        methods=["POST"],
        dependencies=[Depends(verify_ingest_api_key)],
    )

    return router
