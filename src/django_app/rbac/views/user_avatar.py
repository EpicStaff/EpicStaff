from django.http import HttpResponse
from django.utils.http import parse_etags
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.negotiation import BaseContentNegotiation
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rbac.profile.avatar import AvatarDescriptor, UserAvatarReadService

_IMMUTABLE_CACHE_CONTROL = "private, max-age=31536000, immutable"
_REVALIDATE_CACHE_CONTROL = "private, no-cache"


class _IgnoreAcceptNegotiation(BaseContentNegotiation):
    """Pick the first renderer whatever the Accept header says.

    The image itself bypasses renderers; they only render error bodies. Without
    this, an `Accept: image/png` request would be refused with 406 before the
    view runs.
    """

    def select_parser(self, request, parsers):
        return parsers[0] if parsers else None

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


def _matches_if_none_match(header: str, etag: str) -> bool:
    # RFC 9110 compares If-None-Match weakly: W/"x" matches "x", and * matches any.
    client_etags = parse_etags(header)
    return "*" in client_etags or any(
        client_etag.removeprefix("W/") == etag for client_etag in client_etags
    )


class UserAvatarView(APIView):
    """Serve a user's avatar image to anyone who may see that user.

    No organization context: an avatar belongs to the user, and the read service
    decides visibility from the memberships the caller and the user share.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]
    content_negotiation_class = _IgnoreAcceptNegotiation

    _service = UserAvatarReadService()

    @extend_schema(
        summary="Get a user's avatar image",
        parameters=[
            OpenApiParameter(
                "v",
                OpenApiTypes.STR,
                required=False,
                description=(
                    "Avatar version from `avatar_url`. With it the response is cached "
                    "for a year and a stale version is 404; without it the client "
                    "must revalidate with If-None-Match."
                ),
            ),
        ],
        responses={
            (200, "image/*"): OpenApiTypes.BINARY,
            304: OpenApiResponse(description="Not modified: the cached image is current"),
            404: OpenApiResponse(
                description="Unknown or not visible user, no avatar, or a stale version"
            ),
        },
    )
    def get(self, request, user_id: int):
        descriptor = self._service.resolve(request.user, user_id, request.query_params.get("v"))
        cache_control = (
            _IMMUTABLE_CACHE_CONTROL if descriptor.immutable else _REVALIDATE_CACHE_CONTROL
        )
        if _matches_if_none_match(request.headers.get("If-None-Match", ""), descriptor.etag):
            not_modified = HttpResponse(status=304)
            not_modified["ETag"] = descriptor.etag
            not_modified["Cache-Control"] = cache_control
            return not_modified
        return self._image_response(descriptor, cache_control)

    def _image_response(self, descriptor: AvatarDescriptor, cache_control: str) -> HttpResponse:
        image = self._service.read(descriptor)
        response = HttpResponse(image, content_type=descriptor.content_type)
        response["Content-Length"] = str(len(image))
        response["ETag"] = descriptor.etag
        response["Cache-Control"] = cache_control
        response["X-Content-Type-Options"] = "nosniff"
        return response
