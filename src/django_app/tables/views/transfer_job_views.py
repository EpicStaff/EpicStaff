from collections.abc import Generator
from urllib.parse import urlencode
from uuid import UUID

from django.http import StreamingHttpResponse
from django.urls import reverse
from django.utils.http import content_disposition_header
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rbac.access.asserts import assert_row_org_permission
from rbac.access.principals import user_api_key_org_id
from rbac.authorship import resolve_author
from rbac.identity.tickets import (
    TRANSFER_DOWNLOAD_TICKET_TTL_SECONDS,
    transfer_download_ticket_service,
)
from rbac.models.enums import Permission
from rbac.scoping.mixins import OrgScopedResolverMixin
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed, NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tables.exceptions import TransferJobNotReadyError
from tables.import_export.enums import EntityType
from tables.import_export.permissions import ENTITY_RESOURCE_MAP
from tables.models import TransferJob
from tables.serializers.transfer_job_serializers import (
    TransferJobDownloadTicketSerializer,
    TransferJobSerializer,
)
from tables.services.transfer_jobs.archive_store import TransferArchiveStore

TICKET_QUERY_PARAM = "ticket"


class TransferJobViewSet(OrgScopedResolverMixin, viewsets.GenericViewSet):
    """Status and archive download of the caller's own export and import jobs.

    A job is visible only to its creator, in the organization it was started in:
    any other job id, a malformed one included, is a 404. The status needs no
    permission bit (it is the caller's own job); the download re-checks the
    EXPORT right on the job's main entity, which may have been revoked since.

    A browser navigation cannot send the Authorization header, so the download
    also accepts a one-time ticket (`download-ticket`) in its query string
    instead. A ticketed download runs without DRF authentication and
    permissions: the ticket is the credential, and `download` re-authorizes its
    holder against the job's organization.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TransferJobSerializer
    queryset = TransferJob.objects.all()

    def get_permissions(self):
        if self._is_ticketed_download():
            return []
        return super().get_permissions()

    def get_queryset(self):
        # A system API key or a plugin service account owns no jobs.
        author = resolve_author(self.request.user)
        if author is None:
            return TransferJob.objects.none()
        return TransferJob.objects.filter(org_id=self.get_active_org_id(), created_by=author)

    def get_object(self) -> TransferJob:
        job = self.get_queryset().filter(pk=self._job_id()).first()
        if job is None:
            raise NotFound()
        return job

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(
        request=None,
        responses={
            200: TransferJobDownloadTicketSerializer,
            409: OpenApiResponse(description="`job_not_ready`: not a completed export."),
        },
        description=(
            "Issue a one-time URL that downloads the job's archive without the "
            "Authorization header, for a browser to navigate to. The ticket in it "
            f"expires after {TRANSFER_DOWNLOAD_TICKET_TTL_SECONDS} seconds and opens "
            "only this job, once."
        ),
    )
    @action(detail=True, methods=["post"], url_path="download-ticket")
    def download_ticket(self, request, pk=None):
        job = self.get_object()
        api_key_org_id = user_api_key_org_id(request)
        _assert_downloadable(job, request.user, api_key_org_id)

        ticket, _ttl = transfer_download_ticket_service(job.id).issue(
            request.user, api_key_org_id=api_key_org_id
        )
        download_path = reverse("transfer-jobs-download", args=[job.id])
        download_url = f"{download_path}?{urlencode({TICKET_QUERY_PARAM: ticket})}"
        return Response(TransferJobDownloadTicketSerializer({"download_url": download_url}).data)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name=TICKET_QUERY_PARAM,
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description=(
                    "One-time ticket from `download-ticket`, in place of the "
                    "Authorization header. An unknown, expired or used ticket, or one "
                    "issued for another job, is a 404. A HEAD request with a ticket "
                    "is a 405 and leaves the ticket unspent."
                ),
            )
        ],
        responses={
            (200, "application/zip"): OpenApiResponse(
                response=OpenApiTypes.BINARY, description="The export archive."
            ),
            409: OpenApiResponse(description="`job_not_ready`: not a completed export."),
        },
    )
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        if self._is_ticketed_download():
            # DRF routes HEAD here too; only the GET that fetches the archive may
            # spend the single-use ticket.
            if request.method != "GET":
                raise MethodNotAllowed(request.method)
            job = self._redeem_download_ticket(request.query_params[TICKET_QUERY_PARAM])
        else:
            job = self.get_object()
            _assert_downloadable(job, request.user, user_api_key_org_id(request))

        chunks = TransferArchiveStore().iter_chunks(job.archive_key)
        try:
            # Opens the stored archive before the response starts, so a missing
            # one is a 404 instead of a 200 cut off after its headers.
            first_chunk = next(chunks, b"")
        except FileNotFoundError as error:
            raise NotFound("The archive of this job is no longer stored.") from error

        response = StreamingHttpResponse(
            _stream(first_chunk, chunks), content_type="application/zip"
        )
        response["Content-Disposition"] = content_disposition_header(
            as_attachment=True, filename=job.file_name
        )
        return response

    def _is_ticketed_download(self) -> bool:
        # `get_permissions` also runs on a bare instance (schema generation,
        # route sweeps), which has no request.
        request = getattr(self, "request", None)
        return (
            self.action == "download"
            and request is not None
            and TICKET_QUERY_PARAM in request.query_params
        )

    def _job_id(self) -> UUID:
        try:
            return UUID(str(self.kwargs["pk"]))
        except ValueError as error:
            raise NotFound() from error

    def _redeem_download_ticket(self, ticket: str) -> TransferJob:
        """Consume `ticket` and return the job it opens, re-authorizing its holder.

        The ticket is spent before anything else is checked, so it can never be
        tried twice. Whatever the reason it opens nothing (unknown, expired,
        used, issued for another job, holder no longer the job's creator or
        no longer in its organization), the answer is the same 404.
        """
        job_id = self._job_id()
        holder = transfer_download_ticket_service(job_id).consume(ticket)
        if holder is None or not holder.user.is_active:
            raise NotFound()
        job = TransferJob.objects.filter(pk=job_id, created_by=holder.user).first()
        if job is None:
            raise NotFound()
        _assert_downloadable(job, holder.user, holder.api_key_org_id)
        return job


def _assert_downloadable(job: TransferJob, user, api_key_org_id: int | None) -> None:
    if job.kind != TransferJob.Kind.EXPORT or job.status != TransferJob.Status.COMPLETED:
        raise TransferJobNotReadyError()
    assert_row_org_permission(
        user,
        job.org_id,
        ENTITY_RESOURCE_MAP[EntityType(job.main_entity)],
        Permission.EXPORT,
        not_found=NotFound(),
        api_key_org_id=api_key_org_id,
    )


def _stream(
    first_chunk: bytes, chunks: Generator[bytes, None, None]
) -> Generator[bytes, None, None]:
    # Django closes this generator when the response ends, client gone or not,
    # and closing `chunks` releases the storage connection.
    try:
        yield first_chunk
        yield from chunks
    finally:
        chunks.close()
