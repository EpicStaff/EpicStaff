from fastapi.concurrency import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.controllers import health_routes, ingest_routes
from app.core.settings import settings
from app.repositories.factory import build_session_audit_repository


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
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_routes.router)
    app.include_router(ingest_routes.router)

    return app