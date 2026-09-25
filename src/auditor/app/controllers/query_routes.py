from app.core.security import require_audit_action
from app.domains.base import AuditDomain
from app.services.search_pipeline import SearchPipeline
from fastapi import APIRouter, Body, Depends, Request


def build_search_router(domain: AuditDomain) -> APIRouter:
    """Mounts `domain`'s search endpoint at `/api/audit/{domain.name}/search`."""
    router = APIRouter(tags=["Browse"])
    pipeline = SearchPipeline.from_domain(domain)
    search_request_model = domain.api.search_request_model
    search_response_model = domain.api.search_response_model

    @router.post(f"/api/audit/{domain.name}/search", description=domain.api.search_description)
    async def search(
        request: Request,
        body: search_request_model = Body(openapi_examples=domain.api.search_examples),
        claims: dict = Depends(require_audit_action(domain, "read")),
    ) -> search_response_model:
        repository = request.app.state.repositories[domain.name]
        events, next_cursor, partial = await pipeline.search(
            repository,
            body.resolve_filter_node(),
            getattr(body, "match_scope", None),
            org_id=claims["org_id"],
            retention_days=claims["retention_days"],
            cursor=body.cursor,
            size=body.size,
        )
        return search_response_model(
            items=[event.model_dump(mode="json") for event in events],
            next_cursor=next_cursor,
            partial=partial,
        )

    return router
