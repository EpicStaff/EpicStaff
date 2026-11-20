from app.core.security import require_audit_action
from app.domains.base import AuditDomain, BaseScopeArgs
from app.services.search_pipeline import SearchPipeline
from app.swagger_schemas import VALUES_DESCRIPTION
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel

# The lists feed filter checkboxes over small closed vocabularies (target_type
# has a few dozen labels), so 200 leaves ample headroom while bounding the
# aggregation's bucket memory and the response size.
MAX_LISTED_VALUES = 200


class FieldValuesResponse(BaseModel):
    field: str
    values: list[str]


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
            items=[event.public_dump() for event in events],
            next_cursor=next_cursor,
            partial=partial,
        )

    return router


def build_values_router(domain: AuditDomain) -> APIRouter:
    """Mounts `domain`'s value list at `/api/audit/{domain.name}/values/{field}`."""
    router = APIRouter(tags=["Browse"])
    description = VALUES_DESCRIPTION.format(
        fields=", ".join(f"`{field}`" for field in sorted(domain.value_fields)),
        limit=MAX_LISTED_VALUES,
    )

    @router.get(f"/api/audit/{domain.name}/values/{{field}}", description=description)
    async def list_values(
        request: Request,
        field: str,
        claims: dict = Depends(require_audit_action(domain, "read")),
    ) -> FieldValuesResponse:
        if field not in domain.value_fields:
            raise HTTPException(
                status_code=404,
                detail=f"Field {field!r} has no value list in the {domain.name} audit domain",
            )
        query = domain.scoping([], BaseScopeArgs(claims["org_id"], claims["retention_days"]))
        repository = request.app.state.repositories[domain.name]
        values = await repository.distinct_values(query, field, MAX_LISTED_VALUES)
        return FieldValuesResponse(field=field, values=values)

    return router
