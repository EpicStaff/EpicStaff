from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tables.serializers.user_profile_serializers import (
    PasswordChangeConfirmRequestSerializer,
    PasswordChangeConfirmResponseSerializer,
    PasswordChangeRequestRequestSerializer,
    PasswordChangeRequestResponseSerializer,
    ProfilePatchRequestSerializer,
    ProfileResponseSerializer,
)
from tables.services.rbac.authentication import JwtOrApiKeyAuthentication
from tables.services.rbac.user_profile_service import UserProfileService
from tables.services.rbac.user_validation_service import UserValidationService
from tables.throttles import LoginThrottle


def _require_user_context(request):
    """Reject env-seeded API keys (created_by=None → AnonymousUser).
    The profile surface is meaningless without a user identity.
    Inlined per design decision D19 (matches the auth_views.py pattern)."""
    if not getattr(request.user, "is_authenticated", False) or not hasattr(
        request.user, "email"
    ):
        raise PermissionDenied("This endpoint requires a user context.")


class ProfileView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _service = UserProfileService()
    _validator = UserValidationService()

    @extend_schema(
        summary="Get my profile",
        responses={200: ProfileResponseSerializer},
    )
    def get(self, request):
        _require_user_context(request)
        active_org_id = self._extract_active_org_id(request)
        user = self._service.get_profile(request.user, active_org_id=active_org_id)
        return Response(
            ProfileResponseSerializer(user, context={"request": request}).data
        )

    @staticmethod
    def _extract_active_org_id(request):
        raw = request.headers.get("X-Organization-Id")
        if not raw:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None  # Soft-fail: profile is the boot endpoint.

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
        user = request.user
        if "display_name" in cleaned:
            user = self._service.update_display_name(user, cleaned["display_name"])
        user = self._service.get_profile(user)
        return Response(
            ProfileResponseSerializer(user, context={"request": request}).data
        )


class ProfileAvatarView(APIView):
    parser_classes = [MultiPartParser, FormParser]
    authentication_classes = [JwtOrApiKeyAuthentication]
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
            400: OpenApiResponse(
                description="Validation error, file too large, or invalid image"
            ),
        },
    )
    def post(self, request):
        _require_user_context(request)
        uploaded = self._validator.validate_avatar_upload(request.data)
        user = self._service.update_avatar(request.user, uploaded)
        user = self._service.get_profile(user)
        return Response(
            ProfileResponseSerializer(user, context={"request": request}).data
        )

    @extend_schema(
        summary="Remove my avatar",
        responses={204: OpenApiResponse(description="Removed")},
    )
    def delete(self, request):
        _require_user_context(request)
        self._service.clear_avatar(request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class PasswordChangeRequestView(APIView):
    authentication_classes = [JwtOrApiKeyAuthentication]
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
    authentication_classes = [JwtOrApiKeyAuthentication]
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
        return Response({"access": tokens.access, "refresh": tokens.refresh})
