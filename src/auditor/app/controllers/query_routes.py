from fastapi import APIRouter, Body, Depends, Request

from app.core.security import require_audit_action
from app.domains.base import AuditDomain
from app.repositories.compiler import QueryCompiler
from app.services.search_pipeline import SearchPipeline


def build_search_router(domain: AuditDomain) -> APIRouter:
    """Mounts one domain's search endpoint at `/api/audit/{domain.name}/search`
    - this already matches the sessions domain's live path today
    (`/api/audit/sessions/search`), so wiring SESSIONS through this factory
    reproduces the exact same URL.

    Domain-generic: the request/response model types and OpenAPI
    description/examples all come off `domain` (see
    app/domains/base.py::AuditDomain) rather than being imported from
    app.domains.sessions directly - a second domain plugs in its own
    schemas.py without touching this file."""
    router = APIRouter(tags=["Browse"])
    pipeline = SearchPipeline(
        catalog=domain.fields,
        compiler=QueryCompiler(catalog=domain.fields, scoping=domain.scoping),
        computed=domain.computed,
        expander=domain.expander,
        event_model=domain.event_model,
    )
    SearchRequest = domain.api.search_request_model
    SearchResponse = domain.api.search_response_model

    async def _run_search(
        request: Request, body: SearchRequest, claims: dict
    ) -> SearchResponse:
        repository = request.app.state.repositories[domain.name]

        org_id = claims["org_id"]
        retention_days = claims["retention_days"]

        filter_node = body.resolve_filter_node()
        events, next_cursor, partial = await pipeline.search(
            repository,
            filter_node,
            body.match_scope,
            org_id=org_id,
            retention_days=retention_days,
            cursor=body.cursor,
            size=body.size,
        )

        return SearchResponse(
            items=[e.model_dump(mode="json") for e in events],
            next_cursor=next_cursor,
            partial=partial,
        )

    @router.post(
        f"/api/audit/{domain.name}/search", description=domain.api.search_description
    )
    async def search_sessions(
        request: Request,
        body: SearchRequest = Body(openapi_examples=domain.api.search_examples),
        claims: dict = Depends(require_audit_action(domain, "read")),
    ) -> SearchResponse:
        return await _run_search(request, body, claims)

    return router
