from fastapi.concurrency import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.controllers import export_routes, health_routes, ingest_routes, query_routes
from app.core.settings import settings
from app.repositories.factory import build_session_audit_repository

# Tag order here is the order the groups appear in /docs. Each description
# states which of the two authentication schemes the group uses, because that
# is the least obvious thing about this API: producers authenticate with a
# static shared key, end users with a short-lived token minted elsewhere.
OPENAPI_TAGS = [
    {
        "name": "Browse",
        "description": (
            "Read the audit trail. **Auth: `HTTPBearer`** - the short-lived (5 min) "
            "JWT from django_app's `POST /api/audit/token/`, which requires the "
            "`read` action in its `actions` claim. Results are always scoped to "
            "the token's `org_id` and clipped to its `retention_days` window; "
            "neither can be widened by any request parameter."
        ),
    },
    {
        "name": "Export",
        "description": (
            "Export the audit trail as CSV or JSON. **Auth: `HTTPBearer`** with the "
            "`export` action - gated independently of `read`, so a token may browse "
            "without being able to export.\n\n"
            "Asynchronous: `POST` returns a `job_id`, then poll `GET .../{job_id}`, "
            "which answers `{\"status\": \"pending\"}` as JSON until the job "
            "finishes and then serves the file body itself (`500` if it failed)."
        ),
    },
    {
        "name": "Ingest",
        "description": (
            "Write endpoint for producer services (crew, django_app), not for end "
            "users. **Auth: `APIKeyHeader`** - the static `X-API-Key` shared secret, "
            "not a user token.\n\n"
            "Idempotent: each event carries its own `id`, which becomes the "
            "OpenSearch document `_id`, so re-sending a batch overwrites in place "
            "instead of duplicating. This is what makes the client's retry path safe."
        ),
    },
    {
        "name": "Health",
        "description": "Liveness probe. Unauthenticated.",
    },
]


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

    app.include_router(health_routes.router)
    app.include_router(ingest_routes.router)
    app.include_router(query_routes.router)
    app.include_router(export_routes.router)

    return app