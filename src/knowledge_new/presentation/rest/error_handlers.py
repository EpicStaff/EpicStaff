from collections.abc import Callable

from domain.errors import (
    ContentStorageUnavailableError,
    DocumentContentMissingError,
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


_error_handlers: dict[type[Exception], Callable[[Request, Exception], Response]] = {}


def get_error_handlers() -> dict[type[Exception], Callable[[Request, Exception], Response]]:
    return _error_handlers


def create_response(request: Request, status_code: int, code: str, error: Exception) -> Response:
    return Response(
        content={
            "code": code,
            "detail": str(error),
        },
        status_code=status_code,
    )


def registry(*errors: type[Exception]):
    def decorator(fn: Callable[[Request, Exception], Response]):
        for error in errors:
            handler = _error_handlers.get(error)
            if handler is None:
                _error_handlers[error] = fn
            else:
                raise ValueError(f"'{error.__name__}' has had {handler.__name__} handler yet.")
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


@registry(DocumentContentMissingError)
def handle_document_content_missing(request, error: Exception) -> Response:
    # The row is there, its file is not: no retry helps, so it is a 404 with its own code.
    return create_response(
        request, status_codes.HTTP_404_NOT_FOUND, "document_content_missing", error
    )


@registry(ContentStorageUnavailableError)
def handle_content_storage_unavailable(request, error: Exception) -> Response:
    return create_response(
        request, status_codes.HTTP_503_SERVICE_UNAVAILABLE, "storage_unavailable", error
    )


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


@registry(KnowledgeError)
def handle_server_error(request, error: Exception) -> Response:
    logger.exception("Unhandled domain error: {}", error)
    return create_response(
        request, status_codes.HTTP_500_INTERNAL_SERVER_ERROR, "internal_error", error
    )
