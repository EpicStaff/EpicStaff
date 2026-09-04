from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tables.serializers.user_management_serializers import (
    UserCreateRequestSerializer,
    UserResponseSerializer,
)
from tables.services.rbac.authentication import ApiKeyAuthentication, JwtAuthentication
from tables.services.rbac.permissions import IsSuperadmin
from tables.services.rbac.user_management_service import UserManagementService
from tables.services.rbac.user_validation_service import UserValidationService


class UserPagination(PageNumberPagination):
    """Cross-org user list pagination."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class UserAdminViewSet(viewsets.ViewSet):
    """Superadmin-only management of Users (the global account entity).

    GET (list paginated), POST (create with optional initial org+role),
    POST {id}/grant-superadmin/, POST {id}/revoke-superadmin/,
    POST {id}/deactivate/, POST {id}/reactivate/.

    Membership management (add/change-role/remove within an org) is a
    separate, permission-driven surface: /api/admin/memberships/.

    Domain errors raised by the service surface through the project's
    custom_exception_handler envelope; the view layer does not catch
    or translate them.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, IsSuperadmin]
    pagination_class = UserPagination
    lookup_value_regex = "[0-9]+"

    _service = UserManagementService()
    _validator = UserValidationService()

    @extend_schema(
        summary="List users (superadmin)",
        responses={200: UserResponseSerializer(many=True)},
    )
    def list(self, request):
        cleaned = self._validator.validate_list_users_query(request.query_params)
        qs = self._service.list_users(
            actor=request.user,
            email=cleaned["email"],
            is_superadmin=cleaned["is_superadmin"],
            organization_id=cleaned["organization_id"],
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = UserResponseSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)

    @extend_schema(
        summary="Create a user (superadmin)",
        request=UserCreateRequestSerializer,
        responses={
            201: UserResponseSerializer,
            400: OpenApiResponse(description="Validation error or duplicate email"),
            404: OpenApiResponse(description="Organization or role not found"),
        },
    )
    def create(self, request):
        cleaned = self._validator.validate_create_user(request.data)
        user = self._service.create_user(
            actor=request.user,
            email=cleaned["email"],
            password=cleaned["password"],
            organization_id=cleaned["organization_id"],
            role_id=cleaned["role_id"],
        )
        # Re-fetch via the read queryset so memberships[] is prefetched.
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(
            UserResponseSerializer(user, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @action(detail=True, methods=["post"], url_path="grant-superadmin")
    @extend_schema(
        summary="Grant superadmin (superadmin)",
        responses={
            200: UserResponseSerializer,
            404: OpenApiResponse(description="User not found"),
        },
    )
    def grant_superadmin(self, request, pk=None):
        user = self._service.grant_superadmin(
            actor=request.user, target_user_id=int(pk)
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="revoke-superadmin")
    @extend_schema(
        summary="Revoke superadmin (superadmin)",
        responses={
            200: UserResponseSerializer,
            400: OpenApiResponse(description="Cannot revoke last superadmin"),
            404: OpenApiResponse(description="User not found"),
        },
    )
    def revoke_superadmin(self, request, pk=None):
        user = self._service.revoke_superadmin(
            actor=request.user, target_user_id=int(pk)
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    @extend_schema(
        summary="Deactivate a user account (superadmin)",
        responses={
            200: UserResponseSerializer,
            400: OpenApiResponse(
                description="Cannot deactivate the last active superadmin"
            ),
            404: OpenApiResponse(description="User not found"),
        },
    )
    def deactivate(self, request, pk=None):
        user = self._service.set_user_active(
            actor=request.user, target_user_id=int(pk), is_active=False
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="reactivate")
    @extend_schema(
        summary="Reactivate a user account (superadmin)",
        responses={
            200: UserResponseSerializer,
            404: OpenApiResponse(description="User not found"),
        },
    )
    def reactivate(self, request, pk=None):
        user = self._service.set_user_active(
            actor=request.user, target_user_id=int(pk), is_active=True
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)
