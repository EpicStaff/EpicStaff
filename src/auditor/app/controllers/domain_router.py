"""
Assembles one FastAPI APIRouter per audit domain, mounting its
search/export/ingest endpoints. app/main.py loops
app.domains.registry.DOMAINS and mounts one of these per domain - no
domain-specific `include_router` calls live in main.py anymore.
"""

from fastapi import APIRouter

from app.controllers.export_routes import build_export_router
from app.controllers.ingest_routes import build_ingest_router
from app.controllers.query_routes import build_search_router
from app.domains.base import AuditDomain


def build_domain_router(domain: AuditDomain) -> APIRouter:
    router = APIRouter()
    router.include_router(build_search_router(domain))
    router.include_router(build_export_router(domain))
    router.include_router(build_ingest_router(domain))
    return router
