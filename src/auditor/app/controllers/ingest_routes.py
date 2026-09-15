from fastapi import APIRouter, Depends, Request
from loguru import logger

from app.core.security import verify_ingest_api_key
from src.shared.models import SessionAuditEvent

router = APIRouter(tags=["Ingest"])


@router.post("/api/audit/events", dependencies=[Depends(verify_ingest_api_key)])
async def ingest_events(events: list[SessionAuditEvent], request: Request):
    logger.info(f"Ingesting {len(events)} audit event(s): {[e.id for e in events]}")
    await request.app.state.session_audit_repository.write_batch(events)
    logger.info(f"Wrote {len(events)} audit event(s) to the repository")
    return {"received": len(events)}
