from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.models.user import TOUR_KEY_MAX_LENGTH, TOURS_MAX_PER_USER

from rbac.access.principals import user_api_key_org_id
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rbac.identity.refresh_cookie import (
    get_refresh_from_cookie,
    read_remember_me_claim,
    set_refresh_cookie,
)
from rbac.profile.service import UserProfileService
from rbac.serializers.profile import (
    PasswordChangeConfirmRequestSerializer,
    PasswordChangeConfirmResponseSerializer,
    PasswordChangeRequestRequestSerializer,
    PasswordChangeRequestResponseSerializer,
    ProfilePatchRequestSerializer,
    ProfileResponseSerializer,
)
from rbac.signals import profile_updated
from rbac.throttles import LoginThrottle
from rbac.validation.user import UserValidationService


def _require_user_context(request):
    """Reject principals without a user identity (system API keys →
    SystemServicePrincipal has no email).
    The profile surface is meaningless without a user identity.
    Inlined per design decision D19 (matches the auth_views.py pattern)."""
    if not getattr(request.user, "is_authenticated", False) or not hasattr(request.user, "email"):
        raise PermissionDenied("This endpoint requires a user context.")


def _extract_active_org_id(request):
    key_org_id = user_api_key_org_id(request)
    if key_org_id is not None:
        return key_org_id
    raw = request.headers.get("X-Organization-Id")
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None  # Soft-fail: profile is the boot endpoint.


class ProfileView(APIView):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = UserProfileService()
    _validator = UserValidationService()

    @extend_schema(
        summary="Get my profile",
        responses={200: ProfileResponseSerializer},
    )
    def get(self, request):
        _require_user_context(request)
        active_org_id = _extract_active_org_id(request)
        user = self._service.get_profile(
            request.user,
            active_org_id=active_org_id,
            api_key_org_id=user_api_key_org_id(request),
        )
        return Response(ProfileResponseSerializer(user, context={"request": request}).data)

    @extend_schema(
        summary="Update my profile",
        request=ProfilePatchRequestSerializer,
        responses={
            200: ProfileResponseSerializer,
            400: OpenApiResponse(description="Validation error"),
        },
    )
    def patch(self, request):
        _require_user_context(request)
        cleaned = self._validator.validate_profile_patch(request.data)
        user = self._service.update_profile(request.user, cleaned)
        user = self._service.get_profile(user, api_key_org_id=user_api_key_org_id(request))
        if "display_name" in cleaned:
            profile_updated.send(sender=type(user), user=user)
        return Response(ProfileResponseSerializer(user, context={"request": request}).data)


class ProfileAvatarView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = UserProfileService()
    _validator = UserValidationService()

    @extend_schema(
        summary="Upload or replace my avatar",
        # Inline multipart schema so Swagger UI renders a file picker.
        request={
            "multipart/form-data": {
                "type": "object",
                "properties": {
                    "avatar": {"type": "string", "format": "binary"},
                },
                "required": ["avatar"],
            }
        },
        responses={
            200: ProfileResponseSerializer,
            400: OpenApiResponse(description="Validation error, file too large, or invalid image"),
        },
    )
    def post(self, request):
        _require_user_context(request)
        uploaded = self._validator.validate_avatar_upload(request.data)
        user = self._service.update_avatar(request.user, uploaded)
        user = self._service.get_profile(user, api_key_org_id=user_api_key_org_id(request))
        profile_updated.send(sender=type(user), user=user)
        return Response(ProfileResponseSerializer(user, context={"request": request}).data)

    @extend_schema(
        summary="Remove my avatar",
        responses={204: OpenApiResponse(description="Removed")},
    )
    def delete(self, request):
        _require_user_context(request)
        self._service.clear_avatar(request.user)
        user = self._service.get_profile(request.user)
        profile_updated.send(sender=type(user), user=user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileTourCompleteView(APIView):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = UserProfileService()
    _validator = UserValidationService()

    @extend_schema(
        summary="Mark a guided tour as completed or skipped for me",
        description=(
            "Idempotent: repeated calls for the same tour keep the first completion time. "
            "The tour appears in `completed_tours` of the returned profile."
        ),
        parameters=[
            OpenApiParameter(
                "tour_key",
                OpenApiTypes.STR,
                OpenApiParameter.PATH,
                description=(
                    "Lowercase letters and digits in words joined by single hyphens, "
                    f"at most {TOUR_KEY_MAX_LENGTH} characters, e.g. quick-start."
                ),
            )
        ],
        request=None,
        responses={
            200: ProfileResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "`invalid`: malformed tour key, details in `errors`. "
                    f"`tour_limit_exceeded`: {TOURS_MAX_PER_USER} other tours already completed."
                )
            ),
        },
    )
    def post(self, request, tour_key):
        _require_user_context(request)
        tour_key = self._validator.validate_tour_key(tour_key)
        self._service.complete_tour(request.user, tour_key)
        # The response is the full profile, so render it with the same org context as GET
        # rather than with null active-org fields.
        user = self._service.get_profile(
            request.user,
            active_org_id=_extract_active_org_id(request),
            api_key_org_id=user_api_key_org_id(request),
        )
        return Response(ProfileResponseSerializer(user, context={"request": request}).data)


class PasswordChangeRequestView(APIView):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]
    throttle_classes = [LoginThrottle]

    _service = UserProfileService()
    _validator = UserValidationService()

    @extend_schema(
        summary="Step 1: verify current password and issue a single-use ticket",
        request=PasswordChangeRequestRequestSerializer,
        responses={
            200: PasswordChangeRequestResponseSerializer,
            400: OpenApiResponse(description="Wrong current password"),
            429: OpenApiResponse(description="Too many attempts"),
        },
    )
    def post(self, request):
        _require_user_context(request)
        cleaned = self._validator.validate_password_change_request(request.data)
        ticket, expires_in = self._service.password_change_request(
            request.user, cleaned["current_password"]
        )
        return Response({"ticket": ticket, "expires_in": expires_in})


class PasswordChangeConfirmView(APIView):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = UserProfileService()
    _validator = UserValidationService()

    @extend_schema(
        summary="Step 2: consume ticket, set new password, rotate JWT pair",
        request=PasswordChangeConfirmRequestSerializer,
        responses={
            200: PasswordChangeConfirmResponseSerializer,
            400: OpenApiResponse(description="Invalid ticket or weak new password"),
        },
    )
    def post(self, request):
        _require_user_context(request)
        cleaned = self._validator.validate_password_change_confirm(request.data)
        tokens = self._service.password_change_confirm(
            request.user, cleaned["ticket"], cleaned["new_password"]
        )
        # Preserve remember-me across the rotated cookie.
        remember_me = read_remember_me_claim(get_refresh_from_cookie(request))
        response = Response({"access": tokens.access})
        set_refresh_cookie(response, tokens.refresh, remember_me=remember_me)
        return response
