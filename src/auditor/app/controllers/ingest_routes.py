from fastapi import APIRouter, Depends, Request

from app.core.security import verify_ingest_api_key
from src.shared.models import SessionAuditEvent

router = APIRouter()


@router.post("/api/audit/events", dependencies=[Depends(verify_ingest_api_key)])
async def ingest_events(events: list[SessionAuditEvent], request: Request):
    await request.app.state.session_audit_repository.write_batch(events)
    return {"received": len(events)}
