from collections.abc import Callable

from domain.errors import (
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    EntityNotFoundError,
    GraphArtifactsNotReadyError,
    GraphNotIndexedError,
    GraphRagConfigNotFoundError,
    InvalidArtifactArchiveError,
    KnowledgeError,
    NotRunningOperationError,
    RagInProcessingError,
    RagNotFoundError,
    RelationshipNotFoundError,
    UnsupportedError,
)
from litestar import Request, Response, status_codes
from loguru import logger
from presentation.rest.disconnect import ClientDisconnectedError

__all__ = ["get_error_handlers"]

# Not an IANA code: nginx's "client closed request", for a response nobody will read.
HTTP_499_CLIENT_CLOSED_REQUEST = 499

INTERNAL_ERROR_DETAIL = "The knowledge service failed to process the request."


ErrorHandlerKey = type[Exception] | int

_error_handlers: dict[ErrorHandlerKey, Callable[[Request, Exception], Response]] = {}


def get_error_handlers() -> dict[ErrorHandlerKey, Callable[[Request, Exception], Response]]:
    return _error_handlers


def create_response(request: Request, status_code: int, code: str, error: Exception) -> Response:
    return Response(
        content={
            "code": code,
            "detail": str(error),
        },
        status_code=status_code,
    )


def registry(*errors: ErrorHandlerKey):
    def decorator(fn: Callable[[Request, Exception], Response]):
        for error in errors:
            handler = _error_handlers.get(error)
            if handler is None:
                _error_handlers[error] = fn
            else:
                raise ValueError(f"'{error!r}' has had {handler.__name__} handler yet.")
        return fn

    return decorator


@registry(
    RagNotFoundError,
    DocumentNotFoundError,
    EmbeddingConfigNotFoundError,
    EntityNotFoundError,
    GraphRagConfigNotFoundError,
    NotRunningOperationError,
    RelationshipNotFoundError,
)
def handler_not_found(request: Request, error: Exception) -> Response:
    return create_response(request, status_codes.HTTP_404_NOT_FOUND, "not_found", error)


@registry(GraphNotIndexedError)
def handler_graph_not_indexed(request: Request, error: Exception) -> Response:
    # The RAG exists but has no index output yet: a state the caller can resolve by
    # indexing, not a missing resource. django_app recognises the code and tells the
    # browser so.
    return create_response(request, status_codes.HTTP_409_CONFLICT, "graph_not_indexed", error)


@registry(UnsupportedError)
def handler_unsupported(request, error: Exception) -> Response:
    return create_response(request, status_codes.HTTP_400_BAD_REQUEST, "unsupported", error)


@registry(InvalidArtifactArchiveError)
def handle_invalid_artifact_archive(request, error: Exception) -> Response:
    return create_response(
        request, status_codes.HTTP_400_BAD_REQUEST, "invalid_artifact_archive", error
    )


@registry(GraphArtifactsNotReadyError)
def handle_graph_artifacts_not_ready(request, error: Exception) -> Response:
    return create_response(
        request, status_codes.HTTP_409_CONFLICT, "graph_artifacts_not_ready", error
    )


@registry(RagInProcessingError)
def handle_rag_in_processing(request, error: Exception) -> Response:
    return create_response(request, status_codes.HTTP_409_CONFLICT, "rag_in_processing", error)


@registry(ClientDisconnectedError)
def handle_client_disconnected(request: Request, error: Exception) -> Response:
    logger.info("Client disconnected from {}; the request was cancelled.", request.url.path)
    return Response(content=b"", status_code=HTTP_499_CLIENT_CLOSED_REQUEST)


# Registered by status code, Litestar's fallback for any exception that no handler
# claims by type. Without it an unexpected error is answered with Litestar's own body
# (a traceback while KNOWLEDGE_DEBUG is on) and, with debug off, is not logged at all.
@registry(KnowledgeError, status_codes.HTTP_500_INTERNAL_SERVER_ERROR)
def handle_server_error(request: Request, error: Exception) -> Response:
    """Answer a server-side failure with a fixed message and log the exception.

    The exception text describes this service's internals (a provider or driver
    error, a file path), not the caller's request, and some callers pass a 5xx body
    on to users and the LLM. The full exception goes to the server log only.
    """
    logger.opt(exception=error).error(
        "Unhandled {error_type} on {method} {path}",
        error_type=type(error).__name__,
        method=request.method,
        path=request.url.path,
    )
    return Response(
        content={"code": "internal_error", "detail": INTERNAL_ERROR_DETAIL},
        status_code=status_codes.HTTP_500_INTERNAL_SERVER_ERROR,
    )
