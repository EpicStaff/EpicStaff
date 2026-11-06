from collections.abc import Generator
from uuid import UUID

from django.http import StreamingHttpResponse
from django.utils.http import content_disposition_header
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rbac.access.asserts import assert_org_permission
from rbac.authorship import resolve_author
from rbac.models.enums import Permission
from rbac.scoping.mixins import OrgScopedResolverMixin
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tables.exceptions import TransferJobNotReadyError
from tables.import_export.enums import EntityType
from tables.import_export.permissions import ENTITY_RESOURCE_MAP
from tables.models import TransferJob
from tables.serializers.transfer_job_serializers import TransferJobSerializer
from tables.services.transfer_jobs.archive_store import TransferArchiveStore


class TransferJobViewSet(OrgScopedResolverMixin, viewsets.GenericViewSet):
    """Status and archive download of the caller's own export and import jobs.

    A job is visible only to its creator, in the organization it was started in:
    any other job id, a malformed one included, is a 404. The status needs no
    permission bit (it is the caller's own job); the download re-checks the
    EXPORT right on the job's main entity, which may have been revoked since.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TransferJobSerializer
    queryset = TransferJob.objects.all()

    def get_queryset(self):
        # A system API key or a plugin service account owns no jobs.
        author = resolve_author(self.request.user)
        if author is None:
            return TransferJob.objects.none()
        return TransferJob.objects.filter(org_id=self.get_active_org_id(), created_by=author)

    def get_object(self) -> TransferJob:
        try:
            job_id = UUID(str(self.kwargs["pk"]))
        except ValueError as error:
            raise NotFound() from error
        job = self.get_queryset().filter(pk=job_id).first()
        if job is None:
            raise NotFound()
        return job

    def retrieve(self, request, pk=None):
        return Response(self.get_serializer(self.get_object()).data)

    @extend_schema(
        responses={
            (200, "application/zip"): OpenApiResponse(
                response=OpenApiTypes.BINARY, description="The export archive."
            ),
            409: OpenApiResponse(description="`job_not_ready`: not a completed export."),
        }
    )
    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        job = self.get_object()
        if job.kind != TransferJob.Kind.EXPORT or job.status != TransferJob.Status.COMPLETED:
            raise TransferJobNotReadyError()
        assert_org_permission(
            request.user,
            job.org_id,
            ENTITY_RESOURCE_MAP[EntityType(job.main_entity)],
            Permission.EXPORT,
        )

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
