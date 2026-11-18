from asgiref.sync import sync_to_async
from rbac.access.asserts import assert_org_permission
from rbac.models.enums import Permission
from rest_framework.exceptions import (
    APIException,
    MethodNotAllowed,
    PermissionDenied,
    ValidationError,
)
from rest_framework.request import Request
from tables.exceptions import OverwriteNotPermitted
from tables.services.storage_service import upload as upload_service
from tables.services.storage_service.archive_unpacking.names import is_archive_name
from tables.views.raw_asgi import (
    ClientDisconnectedError,
    authorize_request,
    declared_size,
    reject_non_utf8_query,
    request_body_chunks,
    send_error,
    send_json,
    serve_like_asgi_handler,
)
from tables.views.storage_bin_purge_access import StorageBinPurgeAccess
from tables.views.storage_views import StorageAPIView
from utils.logger import logger

UPLOAD_STREAM_ACTION = "upload_stream"

# Routed by asgi.py, not a URLconf; nginx's template and StorageApiService repeat this literal.
UPLOAD_STREAM_PATH = "/api/storage/upload/stream"


async def upload_stream_app(scope, receive, send) -> None:
    """ASGI app for the upload stream, wrapped like ASGIHandler: own sync thread and signals."""
    await serve_like_asgi_handler(_serve_upload, scope, receive, send)


async def _serve_upload(scope, receive, send) -> None:
    """Check access, hand the request body to the upload service, answer with JSON."""
    try:
        method = scope.get("method")
        if method != "POST":
            raise MethodNotAllowed(method or "")

        reject_non_utf8_query(scope)
        # Check auth, permissions (FILES:CREATE) and throttling the same way StorageAPIView does.
        request, org_id = await sync_to_async(_check_access)(scope)
        bin_access = await sync_to_async(StorageBinPurgeAccess.for_request)(request, org_id)

        path = request.query_params.get("path", "")
        filename = request.query_params.get("filename", "")
        if not filename:
            raise ValidationError({"filename": "Query param 'filename' is required."})

        # Only builds the chunk generator: the service reads the body later, after checks and a slot.
        chunks = request_body_chunks(receive)
        body_size = declared_size(request)
        # The file name decides the route: archive or plain file.
        upload = (
            upload_service.upload_archive
            if is_archive_name(filename)
            else upload_service.upload_file
        )
        # Authenticated in _check_access's sync thread and cached on the request, so reading
        # it here does no I/O.
        user = request.user
        # A plain file streams straight to storage; an archive is buffered first.
        result = await upload(
            org_id,
            path,
            filename,
            chunks,
            body_size,
            authorize_overwrite=_overwrite_authorizer(user, org_id),
            user=user,
            bin_purge=bin_access.grant,
        )
        result["recycle_bin_purged"] = bin_access.render(result["recycle_bin_purged"])

        await send_json(send, scope, 200, {"status": "DONE", **result})

    except APIException as exc:
        await send_error(send, scope, exc)
    except ClientDisconnectedError:
        logger.info("Streaming upload aborted: client disconnected")
    except Exception as exc:
        logger.exception("Streaming upload failed")
        await send_error(send, scope, exc)


def _check_access(scope) -> tuple[Request, int]:
    """Authenticate and authorize exactly as StorageAPIView would; return the request and org id."""
    view = StorageAPIView()
    request = authorize_request(view, scope, UPLOAD_STREAM_ACTION)
    return request, view.get_active_org_id()


def _overwrite_authorizer(user, org_id: int):
    """Build the check run when a file is already at the target: replacing needs UPDATE."""

    def authorize_overwrite() -> None:
        try:
            assert_org_permission(
                user, org_id, StorageAPIView.rbac_resource_type, Permission.UPDATE
            )
        except PermissionDenied as exc:
            raise OverwriteNotPermitted() from exc

    return authorize_overwrite
