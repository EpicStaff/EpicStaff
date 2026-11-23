from http import HTTPStatus

import pydantic
from django.core.exceptions import PermissionDenied
from django.db import OperationalError
from django.http import Http404, JsonResponse
from django.utils.log import log_response
from django_app.settings import DEBUG
from foundation.schemas import (
    INTERNAL_ERROR_DETAIL,
    UNKNOWN_ERROR_CODE,
    ErrorDetailSchema,
    ErrorResponseSchema,
)
from foundation.transport.http.errors import (
    ClientConnectionError,
    ClientError,
    ClientNotFoundError,
    ClientRateLimitError,
    ClientValidationError,
)
from psycopg_pool import PoolTimeout
from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotFound,
    Throttled,
    ValidationError,
)
from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
from rest_framework.response import Response
from rest_framework.settings import api_settings
from rest_framework.views import exception_handler, set_rollback
from tables.clients.errors import ClientError as OutboundClientError

from utils.exceptions import DatabasePoolExhaustedError
from utils.logger import logger

# Keys DRF generates itself for an error of the whole request or object, not of a field.
_UNLABELLED_KEYS = frozenset({api_settings.NON_FIELD_ERRORS_KEY, "detail"})

# Enough of an upstream body to tell what went wrong from the log, not a whole HTML page.
_LOGGED_UPSTREAM_BODY_LIMIT = 2000


def render_error(status_code: int, items: list[ErrorDetailSchema]) -> dict:
    """Return the body of an error answer: `{type, errors: [{code, detail, attr, context}]}`.

    Every item carries all four keys, `attr` and `context` as null when absent, so a
    client reads one shape whatever the status code.
    """
    return ErrorResponseSchema.for_status(status_code, items).model_dump(mode="json")


def render_api_exception(exc: APIException) -> dict:
    """Return the response body the exception handler would answer `exc` with.

    Only the body: the caller sets the status (`exc.status_code`) and any headers the
    handler would add, such as `Retry-After` or `WWW-Authenticate`. For code that builds
    its own response instead of raising: a middleware, a streaming view, or a view that
    must also change the response (clear a cookie).
    """
    return render_error(exc.status_code, _api_exception_items(exc))


def _join_attr(prefix: str | None, key) -> str:
    return str(key) if prefix is None else f"{prefix}.{key}"


def _error_items(
    detail, context: dict | None, *, default_code: str, attr: str | None = None
) -> list[ErrorDetailSchema]:
    """Turn DRF's error detail into one item per message.

    A dict nests by field name and a list of dicts (a `many=True` serializer) by
    index, both joined into a dotted `attr` such as `classification_decision_table_node_list.3.prompt_configs.1.result_variable`.
    `non_field_errors` and `detail` name no field, so they add nothing to the path.
    Each message keeps the code DRF gave it (`required`, `blank`, `unique`, or the
    exception's own code); `context` goes on every item.
    """
    if isinstance(detail, dict):
        return [
            item
            for key, value in detail.items()
            for item in _error_items(
                value,
                context,
                default_code=default_code,
                attr=attr if key in _UNLABELLED_KEYS else _join_attr(attr, key),
            )
        ]

    if isinstance(detail, (list, tuple)):
        return [
            item
            for index, value in enumerate(detail)
            for item in _error_items(
                value,
                context,
                default_code=default_code,
                # A list of messages belongs to the field itself; a list of objects or
                # lists is one entry per position.
                attr=_join_attr(attr, index) if isinstance(value, (dict, list, tuple)) else attr,
            )
        ]

    text = str(detail)
    if not text:
        return []
    return [
        ErrorDetailSchema(
            code=getattr(detail, "code", None) or default_code,
            detail=text,
            attr=attr,
            context=context,
        )
    ]


def _api_exception_items(exc: APIException) -> list[ErrorDetailSchema]:
    context = getattr(exc, "context", None)
    context = context if isinstance(context, dict) else None

    if isinstance(exc, AuthenticationFailed) and isinstance(exc.detail, dict):
        # simplejwt raises `{"detail", "code", "messages"}`: one refusal, explained
        # once. `messages` lists every token class it tried, which says nothing more.
        code = exc.detail.get("code") or exc.default_code
        text = exc.detail.get("detail") or exc.default_detail
        return [ErrorDetailSchema(code=str(code), detail=str(text), context=context)]

    items = _error_items(exc.detail, context, default_code=exc.default_code)
    # An empty detail still has to say something: `errors` is never empty.
    return items or [
        ErrorDetailSchema(code=exc.default_code, detail=str(exc.default_detail), context=context)
    ]


def _status_code_name(status_code: int) -> str:
    """The status as a code name, the way every service in the project spells it."""
    try:
        return HTTPStatus(status_code).phrase.lower().replace(" ", "_")
    except ValueError:
        # A status outside the standard table: there is no phrase to name it with.
        return "client_error"


def _upstream_envelope(exc: ClientError) -> tuple[int, ErrorResponseSchema] | None:
    """Return the status and envelope of an upstream 4xx answered in the shared shape.

    Only a refusal of the caller's own request is handed on: an upstream 5xx is this
    gateway's dependency failing, which the caller is told in this service's words.
    """
    response = getattr(exc, "response", None)
    if response is None or not status.is_client_error(response.status_code):
        return None
    try:
        envelope = ErrorResponseSchema.model_validate_json(response.text)
    except pydantic.ValidationError:
        return None
    if not envelope.errors:
        return None
    return response.status_code, envelope


def client_error_as_api_exception(exc: ClientError) -> APIException:
    """Translate a transport error from a proxied microservice into a DRF exception.

    An upstream 4xx answered in the shared envelope already says what is wrong in
    words meant for the caller, so its details are kept, collapsed into one message:
    the first item's code and every item's detail, without `attr` or `context`. That
    suits a caller reporting one message (a transfer job); `custom_exception_handler`
    hands the envelope on whole before it gets here. Any other answer can be an
    HTML page or a service's internals, so it goes to the log and the caller gets a
    fixed text. An upstream 4xx is the caller's own request coming back refused, so it
    keeps its status: a conflict stays a conflict rather than becoming a gateway failure the
    caller can do nothing about. A dependency that could not be reached at all is
    service unavailable, which tells the caller the request is worth retrying. What is
    left - a timeout, an upstream 5xx, a response with no status at all - is this
    gateway's dependency failing, and is reported as a bad gateway.
    """
    upstream = _upstream_envelope(exc)
    if upstream is not None:
        upstream_status, envelope = upstream
        return _api_exception(
            upstream_status, envelope.errors[0].code, [item.detail for item in envelope.errors]
        )

    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    logger.warning(
        "Upstream service call failed: {error_type} (status {status_code}): {body}",
        error_type=type(exc).__name__,
        status_code=status_code,
        body=response.text[:_LOGGED_UPSTREAM_BODY_LIMIT] if response is not None else str(exc),
    )

    if isinstance(exc, ClientNotFoundError):
        return NotFound()
    if isinstance(exc, ClientValidationError):
        return ValidationError()
    if isinstance(exc, ClientRateLimitError):
        return Throttled()
    if isinstance(exc, ClientConnectionError):
        return _api_exception(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "upstream_service_unreachable",
            "A service this request depends on could not be reached. Try again later.",
        )
    if status_code is not None and status.is_client_error(status_code):
        return _api_exception(
            status_code,
            _status_code_name(status_code),
            "A service this request depends on refused it.",
        )
    return _api_exception(
        status.HTTP_502_BAD_GATEWAY,
        "upstream_service_error",
        "A service this request depends on failed.",
    )


def _api_exception(status_code: int, code: str, detail: str | list[str]) -> APIException:
    error = APIException(detail, code=code)
    error.status_code = status_code
    error.default_code = code
    return error


def _outbound_client_error_as_api_exception(exc: OutboundClientError) -> APIException:
    """Translate an error of an outbound service client (`tables.clients`) into a DRF exception.

    The status code is the client error's own. The message is the error class's
    static `public_detail`: `detail` can carry the upstream response body, which
    goes to the server log only.
    """
    logger.warning(
        "Outbound service call failed: {error_type}: {detail}",
        error_type=type(exc).__name__,
        detail=exc.detail,
    )
    return _api_exception(exc.status_code, exc.code, exc.public_detail)


def _is_database_pool_exhausted(exc: Exception) -> bool:
    """Tell whether `exc` is the pool's timeout waiting for a free connection.

    Django re-raises driver errors as its own `OperationalError` with the original as
    `__cause__`; a `PoolTimeout` raised outside Django's wrapper arrives as it is.
    """
    return isinstance(exc, PoolTimeout) or (
        isinstance(exc, OperationalError) and isinstance(exc.__cause__, PoolTimeout)
    )


def _log_unhandled_exception(exc: Exception, request, response) -> None:
    """Log the traceback of an exception answered with the generic 500.

    Returning a response stops DRF from re-raising, so Django would log only
    the status line. Django's own request logger records it with the
    traceback, and marks the response as logged so that line is not repeated.
    It goes through stdlib `log_response` rather than loguru on purpose: only
    that call marks the response as logged, so a loguru call would leave
    Django to repeat the line.
    """
    path = request.path if request is not None else "unknown path"
    log_response(
        "Internal Server Error: %s",
        path,
        response=response,
        request=request,
        exception=exc,
    )


def custom_exception_handler(exc, context):
    """Render every exception as the shared `{type, errors}` error envelope."""

    # Imported here, not at module level: the secrets package imports the models,
    # and this util must stay importable without the app registry or a cycle via tables.
    from tables.services.secrets.exceptions import (
        ModelEndpointNotSettableError,
        SecretUseDeniedError,
    )

    # DRF's own `exception_handler()` converts Django's `Http404`/
    # `PermissionDenied` into `NotFound`/`PermissionDenied` APIExceptions,
    # but only on its own local `exc` binding -- the caller's `exc` here is
    # left untouched. Without mirroring that conversion, the `isinstance`
    # check below always misses for these two (e.g. `get_object_or_404()`
    # on a queryset the caller isn't allowed to see), and a correct 404/403
    # response falls through to the generic 500 branch.
    if isinstance(exc, Http404):
        exc = NotFound(*exc.args)
    elif isinstance(exc, PermissionDenied):
        exc = DRFPermissionDenied(*exc.args)
    elif isinstance(exc, (SecretUseDeniedError, ModelEndpointNotSettableError)):
        # A domain error raised by a secret check. Rendered as the field error a
        # serializer would report, so the 400 names the field.
        exc = ValidationError(exc.field_errors())
    elif isinstance(exc, ClientError):
        upstream = _upstream_envelope(exc)
        if upstream is not None:
            # The upstream service already said what is wrong with the caller's
            # request, in the shape this API answers with: hand it on as it is.
            upstream_status, envelope = upstream
            set_rollback()
            return Response(render_error(upstream_status, envelope.errors), status=upstream_status)
        exc = client_error_as_api_exception(exc)
    elif isinstance(exc, OutboundClientError):
        exc = _outbound_client_error_as_api_exception(exc)
    elif _is_database_pool_exhausted(exc):
        logger.warning("No pooled database connection freed up in time: {}", exc)
        exc = DatabasePoolExhaustedError()

    response = exception_handler(exc, context)

    if isinstance(exc, APIException):
        response.data = render_error(exc.status_code, _api_exception_items(exc))
        for name, value in getattr(exc, "headers", {}).items():
            response[name] = value
        return response

    if not DEBUG:
        # The client gets a fixed text: the exception, and even its class name, can
        # carry internals such as database driver errors.
        response = JsonResponse(
            render_error(
                status.HTTP_500_INTERNAL_SERVER_ERROR,
                [ErrorDetailSchema(code=UNKNOWN_ERROR_CODE, detail=INTERNAL_ERROR_DETAIL)],
            ),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        _log_unhandled_exception(exc, context.get("request"), response)
        return response

    return response
