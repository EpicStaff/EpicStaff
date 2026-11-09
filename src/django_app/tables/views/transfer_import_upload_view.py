"""Starting an import job by streaming its `.zip` export archive as the raw request body.

Served as raw ASGI apps (routed by `django_app/asgi.py`), so an archive is written to a
temporary file as it arrives instead of being spooled by Django first. Every refusal
answers before a job row exists, and leaves neither the temporary file nor a stored
archive behind. While its body arrives, an upload holds one of the storage uploads'
slots and counts as an unfinished job of its user.
"""

import asyncio
import os
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from rbac.access.asserts import assert_org_permission
from rbac.access.gates import HasOrgPermission
from rbac.authorship import resolve_author
from rbac.models.enums import Permission, ResourceType
from rbac.scoping.mixins import OrgScopedResolverMixin
from rest_framework.exceptions import APIException, MethodNotAllowed, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.serializers import Serializer
from rest_framework.settings import api_settings
from rest_framework.viewsets import ViewSet
from tables.exceptions import (
    ImportArchiveRejectedError,
    ImportArchiveTooLargeError,
    TransferJobRequiresUserError,
)
from tables.import_export.archive import detect_file_kind
from tables.import_export.enums import EntityType
from tables.import_export.permissions import ENTITY_RESOURCE_MAP
from tables.import_export.schemas import ImportSettings
from tables.models.user import User
from tables.serializers.transfer_job_serializers import (
    CollectionImportJobQuerySerializer,
    FlowImportJobQuerySerializer,
)
from tables.services.storage_service.upload.admission import get_upload_admission
from tables.services.storage_service.upload.guards import (
    storage_errors_as_unavailable,
    within_time_limits,
)
from tables.services.transfer_jobs.job_service import (
    TransferJobService,
    import_uploads_in_progress,
)
from tables.throttles import TransferJobCreateThrottle
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
from utils.exception_handler import flatten_error_detail
from utils.logger import logger

IMPORT_JOBS_ACTION = "import_jobs"
# Bytes `detect_file_kind` needs to tell a zip from anything else.
_ZIP_HEAD_SIZE = 4


@dataclass(frozen=True)
class ImportJobRoute:
    """One import-job upload route: its path and the main entity its archives must carry."""

    # Routed by asgi.py, not a URLconf; nginx's template repeats this literal.
    path: str
    entity_type: EntityType
    query_serializer_class: type[Serializer]

    @property
    def resource_type(self) -> ResourceType:
        return ENTITY_RESOURCE_MAP[self.entity_type]


FLOW_IMPORT_JOBS_ROUTE = ImportJobRoute(
    path="/api/graphs/import-jobs/",
    entity_type=EntityType.GRAPH,
    query_serializer_class=FlowImportJobQuerySerializer,
)
COLLECTION_IMPORT_JOBS_ROUTE = ImportJobRoute(
    path="/api/source-collections/import-jobs/",
    entity_type=EntityType.SOURCE_COLLECTION,
    query_serializer_class=CollectionImportJobQuerySerializer,
)
IMPORT_JOB_ROUTES = (FLOW_IMPORT_JOBS_ROUTE, COLLECTION_IMPORT_JOBS_ROUTE)


class TransferImportAccessView(OrgScopedResolverMixin, ViewSet):
    """The checks an import-job upload passes before its body is read; serves no URL.

    Authenticates with the project defaults (API keys included), gates CREATE on the
    route's resource type in the active organization, and throttles with the bucket
    the export jobs use. Built per request with the route's `rbac_resource_type`.
    """

    permission_classes = [IsAuthenticated, HasOrgPermission]
    rbac_action_map = {IMPORT_JOBS_ACTION: Permission.CREATE}
    throttle_classes = [*api_settings.DEFAULT_THROTTLE_CLASSES, TransferJobCreateThrottle]


@dataclass(frozen=True)
class _Admission:
    """Who may start the import, where, and with which settings; the body is not read yet."""

    user: User
    org_id: int
    import_settings: ImportSettings | None
    file_name: str


def import_upload_app(route: ImportJobRoute):
    """Build the ASGI app of `route`, wrapped like ASGIHandler: own sync thread and signals."""

    async def app(scope, receive, send) -> None:
        async def serve(scope, receive, send) -> None:
            await _serve_import_upload(route, scope, receive, send)

        await serve_like_asgi_handler(serve, scope, receive, send)

    return app


async def _serve_import_upload(route: ImportJobRoute, scope, receive, send) -> None:
    """Check access, receive the archive, start the job and answer 202 `{job_id}`."""
    try:
        method = scope.get("method")
        if method != "POST":
            raise MethodNotAllowed(method or "")
        reject_non_utf8_query(scope)
        admission = await sync_to_async(_admit)(scope, route)

        # Each context below releases what it holds on every way out: success,
        # refusal, timeout, disconnect or cancellation.
        with import_uploads_in_progress.hold(
            org_id=admission.org_id, user_id=admission.user.pk
        ) as other_uploads:
            await sync_to_async(TransferJobService().check_limits)(
                user=admission.user,
                org_id=admission.org_id,
                uploads_in_progress=other_uploads,
            )
            # No database connection is held while waiting for a slot or while the body arrives.
            await sync_to_async(close_old_connections)()
            # The storage uploads' slots: 429 past the organization's share, 503 when none frees up.
            async with (
                get_upload_admission().admit(admission.org_id),
                _received_archive(receive) as archive_path,
            ):
                try:
                    with storage_errors_as_unavailable():
                        job = await sync_to_async(TransferJobService().start_import)(
                            user=admission.user,
                            org_id=admission.org_id,
                            entity_type=route.entity_type,
                            settings=admission.import_settings,
                            archive_path=archive_path,
                            file_name=admission.file_name,
                        )
                except ValidationError as error:
                    raise _rejection(error) from error

        await send_json(send, scope, 202, {"job_id": str(job.id)})

    except APIException as exc:
        await send_error(send, scope, exc)
    except ClientDisconnectedError:
        logger.info("Import upload aborted: client disconnected")
    except Exception as exc:
        logger.exception("Import upload failed")
        await send_error(send, scope, exc)


def _admit(scope, route: ImportJobRoute) -> _Admission:
    """Run every check that needs no body, cheapest refusal first.

    Raises:
        NotAuthenticated, PermissionDenied, Throttled: see `authorize_request`.
        TransferJobRequiresUserError: The caller is no user who could own a job.
        ValidationError: An unknown or invalid query parameter.
        ImportArchiveTooLargeError: Content-Length is past `MAX_KNOWLEDGE_ARCHIVE_SIZE`.
        PermissionDenied: `replace_existing` without the UPDATE right.
    """
    view = TransferImportAccessView(rbac_resource_type=route.resource_type)
    request = authorize_request(view, scope, IMPORT_JOBS_ACTION)
    # A job runs with its creator's permissions and only its creator may read it.
    user = resolve_author(request.user)
    if user is None:
        raise TransferJobRequiresUserError()

    query = route.query_serializer_class(data=request.query_params.dict())
    query.is_valid(raise_exception=True)
    settings_data = dict(query.validated_data)
    file_name = settings_data.pop("file_name", "")
    # A route whose query declares no settings (collections) imports with the defaults.
    import_settings = ImportSettings(**settings_data) if settings_data else None
    body_size = declared_size(request)
    if body_size is not None and body_size > settings.MAX_KNOWLEDGE_ARCHIVE_SIZE:
        raise ImportArchiveTooLargeError()

    org_id = view.get_active_org_id()
    if import_settings is not None and import_settings.replace_existing:
        # Replacing overwrites existing items in place; the gate above only checks CREATE.
        assert_org_permission(request.user, org_id, route.resource_type, Permission.UPDATE)
    return _Admission(
        user=user, org_id=org_id, import_settings=import_settings, file_name=file_name
    )


@asynccontextmanager
async def _received_archive(receive):
    """Write the request body to a temporary file and give its path; delete it afterwards.

    Raises:
        ImportArchiveTooLargeError: The body passes `MAX_KNOWLEDGE_ARCHIVE_SIZE`.
        ImportArchiveRejectedError: The body does not start as a zip does.
        UploadIdleTimeout, UploadDurationExceeded: The client is too slow.
        ClientDisconnectedError: The client left mid-upload.
    """
    # The file is ours from here: deleted on every way out, the body read or not.
    file = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)  # noqa: SIM115
    try:
        try:
            await _write_body(receive, file)
        finally:
            file.close()
        yield file.name
    finally:
        os.unlink(file.name)


async def _write_body(receive, file) -> None:
    max_size = settings.MAX_KNOWLEDGE_ARCHIVE_SIZE
    received = 0
    head = b""
    # Content-Length may be absent (a chunked body) or false; the bytes received are the limit.
    async for chunk in within_time_limits(request_body_chunks(receive)):
        received += len(chunk)
        if received > max_size:
            raise ImportArchiveTooLargeError()
        if len(head) < _ZIP_HEAD_SIZE:
            head += chunk[: _ZIP_HEAD_SIZE - len(head)]
            if len(head) == _ZIP_HEAD_SIZE:
                _assert_zip(head)
        await asyncio.to_thread(file.write, chunk)
    if len(head) < _ZIP_HEAD_SIZE:
        _assert_zip(head)


def _assert_zip(head: bytes) -> None:
    if detect_file_kind(head) != "zip":
        raise ImportArchiveRejectedError(
            "invalid_archive",
            "The body is not a zip archive. Import a .json export with the import/ endpoint.",
        )


def _rejection(error: ValidationError) -> ImportArchiveRejectedError:
    """The 400 for an archive the job would refuse, with the code the job would report."""
    detail = error.detail
    if isinstance(detail, dict) and "code" in detail:
        return ImportArchiveRejectedError(
            str(detail["code"]), flatten_error_detail(detail.get("detail", ""))
        )
    return ImportArchiveRejectedError("invalid_file", flatten_error_detail(detail))
