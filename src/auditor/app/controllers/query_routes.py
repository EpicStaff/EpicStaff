from fastapi import APIRouter, Depends, Query, Request

from app.core.security import require_audit_action

router = APIRouter(tags=["Browse"])


@router.get("/api/audit/sessions")
async def list_sessions(
    request: Request,
    cursor: str | None = None,
    size: int = Query(default=50, le=200),
    search: str | None = None,
    claims: dict = Depends(require_audit_action("read")),
):
    """Paginated, org-wide (all projects/graphs) session list - kind='session' rows only."""
    repository = request.app.state.session_audit_repository
    events, next_cursor = await repository.query(
        filters={
            "org_id": claims["org_id"],
            "kind": "session",
            "retention_days": claims.get("retention_days", 0),
            "search": search,
        },
        cursor=cursor,
        size=size,
    )
    return {
        "items": [e.model_dump(mode="json") for e in events],
        "next_cursor": next_cursor,
    }


@router.get("/api/audit/sessions/{session_id}/tree")
async def get_session_tree(session_id: int, request: Request, claims: dict = Depends(require_audit_action("read"))):
    """Full per-node/tool/agent trace for one session - no redaction."""
    repository = request.app.state.session_audit_repository
    events, _ = await repository.query(
        filters={
            "org_id": claims["org_id"],
            "session_id": session_id,
            "retention_days": claims.get("retention_days", 0),
        },
        cursor=None,
        size=1000,  # one session's full tree - not expected to paginate
    )
    return {"items": [e.model_dump(mode="json") for e in events]}
