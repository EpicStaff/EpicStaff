from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tables.serializers.user_management_serializers import UserResponseSerializer
from tables.services.rbac.authentication import ApiKeyAuthentication, JwtAuthentication
from tables.services.rbac.delete.dry_run import parse_dry_run
from tables.services.rbac.delete.service import DeleteService
from tables.services.rbac.permissions import DenyApiKeyAuth, IsSuperadmin
from tables.services.rbac.user_management_service import UserManagementService
from tables.services.rbac.user_validation_service import UserValidationService
from tables.swagger_schemas.user_admin_schema import (
    USERS_CREATE_POST,
    USERS_DEACTIVATE_POST,
    USERS_DESTROY_DELETE,
    USERS_GRANT_SUPERADMIN_POST,
    USERS_LIST_GET,
    USERS_REACTIVATE_POST,
    USERS_REVOKE_SUPERADMIN_POST,
)
from tables.views.cross_org_admin import CrossOrgAdminViewSet

_ORDERING_WHITELIST = {
    "email": "email",
    "created_at": "created_at",
    "display_name": "display_name",
}
_DEFAULT_ORDERING = ("-created_at", "email")


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
    _delete_service = DeleteService()

    def get_permissions(self):
        """Permanent deletion is JWT-only; a leaked key must not erase accounts."""
        if getattr(self, "action", None) == "destroy":
            return [IsAuthenticated(), IsSuperadmin(), DenyApiKeyAuth()]
        return super().get_permissions()

    @extend_schema(**USERS_LIST_GET)
    def list(self, request):
        org_ids = CrossOrgAdminViewSet.parse_org_ids(
            request.query_params.get("org_ids")
        )
        cleaned = self._validator.validate_list_users_query(request.query_params)
        if org_ids is None and cleaned["organization_id"] is not None:
            org_ids = [cleaned["organization_id"]]
        qs = self._service.list_users(
            actor=request.user,
            search=cleaned["search"],
            is_superadmin=cleaned["is_superadmin"],
            org_ids=org_ids,
            status_value=cleaned["status_value"],
            role_id=cleaned["role_id"],
        )
        qs = self._apply_ordering(qs, request.query_params.get("ordering"))
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = UserResponseSerializer(
            page, many=True, context={"request": request}
        )
        return paginator.get_paginated_response(serializer.data)

    def _apply_ordering(self, qs, raw):
        if not raw:
            return qs.order_by(*_DEFAULT_ORDERING)
        descending = raw.startswith("-")
        field = _ORDERING_WHITELIST.get(raw.lstrip("-"))
        if field is None:
            return qs.order_by(*_DEFAULT_ORDERING)
        return qs.order_by(f"-{field}" if descending else field, "id")

    @extend_schema(**USERS_CREATE_POST)
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
    @extend_schema(**USERS_GRANT_SUPERADMIN_POST)
    def grant_superadmin(self, request, pk=None):
        user = self._service.grant_superadmin(
            actor=request.user, target_user_id=int(pk)
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="revoke-superadmin")
    @extend_schema(**USERS_REVOKE_SUPERADMIN_POST)
    def revoke_superadmin(self, request, pk=None):
        user = self._service.revoke_superadmin(
            actor=request.user, target_user_id=int(pk)
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="deactivate")
    @extend_schema(**USERS_DEACTIVATE_POST)
    def deactivate(self, request, pk=None):
        user = self._service.set_user_active(
            actor=request.user, target_user_id=int(pk), value=False
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="reactivate")
    @extend_schema(**USERS_REACTIVATE_POST)
    def reactivate(self, request, pk=None):
        user = self._service.set_user_active(
            actor=request.user, target_user_id=int(pk), value=True
        )
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @extend_schema(**USERS_DESTROY_DELETE)
    def destroy(self, request, pk=None):
        """Permanently delete a user account, or preview the deletion."""
        dry_run = parse_dry_run(request.query_params.get("dry_run"))
        report = self._delete_service.delete(
            target_type="user",
            target_id=int(pk),
            actor=request.user,
            dry_run=dry_run,
        )
        return Response(report)
