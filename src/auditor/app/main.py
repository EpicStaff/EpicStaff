from fastapi.concurrency import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from opensearchpy.exceptions import ConnectionError as OpenSearchConnectionError
from opensearchpy.exceptions import RequestError as OpenSearchRequestError

from app.controllers import health_routes
from app.controllers.domain_router import build_domain_router
from app.core import settings
from app.domains.registry import DOMAINS
from app.domains.sessions.index import SESSIONS_INDEX
from app.filtering.ast import FilterError
from app.repositories.factory import build_audit_repository
from app.db.redis_client import build_redis_client
from app.services.export_job_service import ExportJobService
from app.swagger_schemas import OPENAPI_TAGS
from src.shared.models import SessionAuditEvent


def _extract_opensearch_reason(exc: OpenSearchRequestError) -> str:
    """Pull the most specific human-readable reason out of a RequestError's
    parsed OpenSearch error body (`exc.info`), falling back to `str(exc)` if
    the body doesn't have the expected shape. Never raises itself."""
    info = exc.info
    if not isinstance(info, dict):
        return str(exc)

    error = info.get("error")
    if not isinstance(error, dict):
        return str(exc)

    caused_by = error.get("caused_by")
    if isinstance(caused_by, dict):
        reason = caused_by.get("reason")
        if reason:
            return str(reason)

    root_cause = error.get("root_cause")
    if isinstance(root_cause, list) and root_cause:
        first = root_cause[0]
        if isinstance(first, dict):
            reason = first.get("reason")
            if reason:
                return str(reason)

    reason = error.get("reason")
    if reason:
        return str(reason)

    return str(exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up...")

    app.state.session_audit_repository = build_audit_repository(
        settings, index=SESSIONS_INDEX, model=SessionAuditEvent
    )
    app.state.export_job_service = ExportJobService(build_redis_client(settings))

    yield

    logger.info("Application shutting down...")
    await app.state.session_audit_repository.close()
    await app.state.export_job_service.close()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        docs_url="/docs" if settings.AUDITOR_DEBUG else None,
        redoc_url="/redoc" if settings.AUDITOR_DEBUG else None,
        openapi_url="/openapi.json" if settings.AUDITOR_DEBUG else None,
        openapi_tags=OPENAPI_TAGS,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(FilterError)
    async def _filter_error_handler(request: Request, exc: FilterError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(OpenSearchRequestError)
    async def _opensearch_request_error_handler(
        request: Request, exc: OpenSearchRequestError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=400, content={"detail": _extract_opensearch_reason(exc)}
        )

    @app.exception_handler(OpenSearchConnectionError)
    async def _opensearch_connection_error_handler(
        request: Request, exc: OpenSearchConnectionError
    ) -> JSONResponse:
        logger.warning(f"OpenSearch unreachable: {exc}")
        return JSONResponse(
            status_code=503,
            content={"detail": "Audit search backend is temporarily unavailable"},
        )

    app.include_router(health_routes.router)
    for domain in DOMAINS.values():
        app.include_router(build_domain_router(domain))

    return app
