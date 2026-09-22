from fastapi import APIRouter, Depends, Request
from loguru import logger

from app.core.security import verify_ingest_api_key
from app.domains.base import AuditDomain


def build_ingest_router(domain: AuditDomain) -> APIRouter:
    """Mounts one domain's ingest endpoint at `/api/audit/events` -
    deliberately NOT namespaced under `/api/audit/{domain.name}/...`, same
    rationale as export_routes.py::build_export_router. The request body's
    event type is the domain's own event model, resolved at router-build
    time (FastAPI reads `events.__annotations__` at route-registration
    time, so this file must not use `from __future__ import annotations` -
    that would defer evaluation of the annotation to a string and break
    this closure-captured type)."""
    router = APIRouter(tags=["Ingest"])
    event_model = domain.event_model

    async def ingest_events(events: list[event_model], request: Request):
        logger.info(f"Ingesting {len(events)} audit event(s): {[e.id for e in events]}")
        await request.app.state.session_audit_repository.write_batch(events)
        logger.info(f"Wrote {len(events)} audit event(s) to the repository")
        return {"received": len(events)}

    router.add_api_route(
        "/api/audit/events",
        ingest_events,
        methods=["POST"],
        dependencies=[Depends(verify_ingest_api_key)],
    )

    return router
