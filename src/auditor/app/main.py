from fastapi.concurrency import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

from app.controllers import export_routes, health_routes, ingest_routes, query_routes
from app.core.settings import settings
from app.filtering.ast import FilterError
from app.repositories.factory import build_session_audit_repository
from app.swagger_schemas import OPENAPI_TAGS


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up...")

    app.state.session_audit_repository = build_session_audit_repository(settings)

    yield

    logger.info("Application shutting down...")
    await app.state.session_audit_repository.close()


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application.
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        description=settings.DESCRIPTION,
        version=settings.VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
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

    app.include_router(health_routes.router)
    app.include_router(ingest_routes.router)
    app.include_router(query_routes.router)
    app.include_router(export_routes.router)

    return app