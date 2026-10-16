from app.core.security import verify_ingest_api_key
from app.domains.base import AuditDomain
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from loguru import logger


def _extract_failures(errors: list[dict]) -> list[dict]:
    """Keeps each failed document's OpenSearch status alongside its id, so
    the client can retry a transient 5xx (e.g. a rejected bulk request under
    load) without also retrying a permanent 4xx (e.g. a mapping conflict)
    that will never succeed."""
    failures = []
    for error in errors:
        for item in error.values():
            doc_id = item.get("_id")
            if doc_id is not None:
                failures.append({"id": doc_id, "status": item.get("status")})
    return failures


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

        failures = _extract_failures(errors)
        logger.error(
            "Audit bulk write to {!r} partially failed: {}/{} event(s) not indexed - {}",
            domain.name,
            len(failures),
            len(events),
            failures,
        )
        return JSONResponse(
            {"received": len(events) - len(failures), "failed": failures},
            status_code=207,
        )

    router.add_api_route(
        f"/api/audit/{domain.name}/events",
        ingest_events,
        methods=["POST"],
        dependencies=[Depends(verify_ingest_api_key)],
    )

    return router
