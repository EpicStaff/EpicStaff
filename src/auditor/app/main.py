from collections.abc import Mapping
from http import HTTPStatus

from app.controllers import health_routes
from app.controllers.domain_router import build_domain_router
from app.core import settings
from app.db.redis_client import build_redis_client
from app.domains.base import MissingScopeError
from app.domains.registry import DOMAINS
from app.filtering.ast import FilterError
from app.repositories.base import AuditRepository
from app.repositories.factory import build_audit_repository
from app.services.export_job_service import ExportJobFailedError, ExportJobService
from app.swagger_schemas import OPENAPI_TAGS
from fastapi import FastAPI, Request
from fastapi.concurrency import asynccontextmanager
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from foundation.schemas import (
    INTERNAL_ERROR_DETAIL,
    UNKNOWN_ERROR_CODE,
    ErrorDetailSchema,
    ErrorResponseSchema,
)
from loguru import logger
from opensearchpy.exceptions import ConnectionError as OpenSearchConnectionError
from opensearchpy.exceptions import RequestError as OpenSearchRequestError
from starlette.exceptions import HTTPException as StarletteHTTPException

# The first `loc` entry of a request validation error names the part of the request the
# value came from, not a field, so it never belongs in `attr`.
_REQUEST_PARTS = frozenset({"body", "query", "path", "header", "cookie"})


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


# OpenSearch answers 400 both for bad client input and for malformed DSL this
# service built itself, so the HTTP status is decided by the error types in the
# response. Input-attributable failures (unparseable dates or numbers in a
# filter value, a search_after cursor that does not fit the sort) surface as
# these types; DSL-structure and script failures mean the compiler is at fault
# and win over any input type found alongside them.
_CLIENT_INPUT_ERROR_TYPES = frozenset(
    {
        "illegal_argument_exception",
        "number_format_exception",
        "parse_exception",
        "date_time_parse_exception",
    }
)
_SERVER_FAULT_ERROR_TYPES = frozenset(
    {"parsing_exception", "x_content_parse_exception", "script_exception"}
)


def _collect_opensearch_error_types(exc: OpenSearchRequestError) -> set[str]:
    info = exc.info
    if not isinstance(info, dict) or not isinstance(info.get("error"), dict):
        return set()

    error_types: set[str] = set()
    pending: list = [info["error"]]
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            continue
        if isinstance(node.get("type"), str):
            error_types.add(node["type"])
        pending.append(node.get("caused_by"))
        root_causes = node.get("root_cause")
        if isinstance(root_causes, list):
            pending.extend(root_causes)
    return error_types


def is_client_input_error(exc: OpenSearchRequestError) -> bool:
    error_types = _collect_opensearch_error_types(exc)
    if error_types & _SERVER_FAULT_ERROR_TYPES:
        return False
    return bool(error_types & _CLIENT_INPUT_ERROR_TYPES)


def _error_response(
    status_code: int,
    errors: list[ErrorDetailSchema],
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content=ErrorResponseSchema.for_status(status_code, errors).model_dump(mode="json"),
        headers=headers,
    )


def _internal_error_response() -> JSONResponse:
    return _error_response(
        500, [ErrorDetailSchema(code=UNKNOWN_ERROR_CODE, detail=INTERNAL_ERROR_DETAIL)]
    )


def _validation_error_attr(error: dict) -> str | None:
    # An unparseable body reports the character offset where parsing stopped; that is
    # not a field of the request.
    if error["type"] == "json_invalid":
        return None
    location = error["loc"]
    if location and location[0] in _REQUEST_PARTS:
        location = location[1:]
    return ".".join(str(part) for part in location) or None


def register_exception_handlers(app: FastAPI) -> None:
    """Answer every handled error with foundation's error envelope.

    A server-side failure never answers with the exception's text: the error goes to the
    log with its traceback and the caller reads a fixed sentence.
    """

    @app.exception_handler(FilterError)
    async def _filter_error_handler(request: Request, exc: FilterError) -> JSONResponse:
        return _error_response(400, [ErrorDetailSchema(code="invalid_filter", detail=str(exc))])

    @app.exception_handler(OpenSearchRequestError)
    async def _opensearch_request_error_handler(
        request: Request, exc: OpenSearchRequestError
    ) -> JSONResponse:
        if is_client_input_error(exc):
            return _error_response(
                400,
                [ErrorDetailSchema(code="invalid_query", detail=_extract_opensearch_reason(exc))],
            )
        logger.opt(exception=exc).error(
            "OpenSearch rejected a server-built query: {}", _extract_opensearch_reason(exc)
        )
        return _internal_error_response()

    @app.exception_handler(OpenSearchConnectionError)
    async def _opensearch_connection_error_handler(
        request: Request, exc: OpenSearchConnectionError
    ) -> JSONResponse:
        logger.opt(exception=exc).error("OpenSearch unreachable")
        return _error_response(
            503,
            [
                ErrorDetailSchema(
                    code="search_unavailable",
                    detail="Audit search backend is temporarily unavailable.",
                )
            ],
        )

    @app.exception_handler(Exception)
    async def _server_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # The fallback for any exception no more specific handler claims. Not logged here:
        # Starlette re-raises it after this answer, and the server logs it with its traceback.
        return _internal_error_response()

    @app.exception_handler(MissingScopeError)
    async def _missing_scope_error_handler(
        request: Request, exc: MissingScopeError
    ) -> JSONResponse:
        logger.opt(exception=exc).error("MissingScopeError (tenancy gate failure)")
        return _internal_error_response()

    @app.exception_handler(ExportJobFailedError)
    async def _export_job_failed_handler(
        request: Request, exc: ExportJobFailedError
    ) -> JSONResponse:
        # The export task logged the cause when the job failed; this only reports it.
        return _error_response(500, [ErrorDetailSchema(code=exc.code, detail=exc.detail)])

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        code = HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
        return _error_response(
            exc.status_code,
            [ErrorDetailSchema(code=code, detail=exc.detail)],
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Built from `type`, `msg` and `loc` only: `input` would echo the caller's value.
        return _error_response(
            422,
            [
                ErrorDetailSchema(
                    code=error["type"], detail=error["msg"], attr=_validation_error_attr(error)
                )
                for error in exc.errors()
            ],
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up...")

    app.state.repositories: dict[str, AuditRepository] = {
        domain.name: build_audit_repository(settings, index=domain.index, model=domain.event_model)
        for domain in DOMAINS.values()
    }
    app.state.export_job_service = ExportJobService(build_redis_client(settings))

    yield

    logger.info("Application shutting down...")
    for repository in app.state.repositories.values():
        await repository.close()
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
        root_path="/auditor",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.CORS_ALLOWED_ORIGINS.split(",")],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)

    app.include_router(health_routes.router)
    for domain in DOMAINS.values():
        app.include_router(build_domain_router(domain))

    return app
