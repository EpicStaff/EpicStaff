"""
Assembles one FastAPI APIRouter per audit domain, mounting its
search/export/ingest endpoints, plus its value lists when it declares
`value_fields`. app/main.py loops
app.domains.registry.DOMAINS and mounts one of these per domain - no
domain-specific `include_router` calls live in main.py anymore.
"""

from app.controllers.export_routes import build_export_router
from app.controllers.ingest_routes import build_ingest_router
from app.controllers.query_routes import build_search_router, build_values_router
from app.domains.base import AuditDomain
from fastapi import APIRouter


def build_domain_router(domain: AuditDomain) -> APIRouter:
    router = APIRouter()
    router.include_router(build_search_router(domain))
    if domain.value_fields:
        router.include_router(build_values_router(domain))
    router.include_router(build_export_router(domain))
    router.include_router(build_ingest_router(domain))
    return router
