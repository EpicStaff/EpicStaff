import dataclasses

from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from tables.models.user import User

from rbac.access.gates import IsSuperadmin
from rbac.governance.users import UserManagementService
from rbac.schemas.users import (
    USERS_CREATE_POST,
    USERS_DEACTIVATE_POST,
    USERS_DESTROY_DELETE,
    USERS_GRANT_SUPERADMIN_POST,
    USERS_LIST_GET,
    USERS_REACTIVATE_POST,
    USERS_REVOKE_SUPERADMIN_POST,
)
from rbac.serializers.delete import UserDeleteReportSerializer
from rbac.serializers.users import (
    UserResponseSerializer,
)
from rbac.validation.hard_delete import HardDeleteValidationService
from rbac.validation.user import UserValidationService
from rbac.views.cross_org_base import CrossOrgAdminPagination, CrossOrgAdminViewSet

_ORDERING_WHITELIST = {
    "email": "email",
    "created_at": "created_at",
    "display_name": "display_name",
}
_DEFAULT_ORDERING = ("-created_at", "email")


class UserAdminViewSet(CrossOrgAdminViewSet):
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

    # Names the served model for user-action and plugin-activity records (`model_of`); never
    # queried, every action reads through its own lookup.
    queryset = User.objects.none()
    permission_classes = [IsAuthenticated, IsSuperadmin]
    pagination_class = CrossOrgAdminPagination

    _service = UserManagementService()
    _validator = UserValidationService()
    _hard_delete_validator = HardDeleteValidationService()

    @extend_schema(**USERS_LIST_GET)
    def list(self, request):
        org_ids = self.parse_org_ids(request.query_params.get("org_ids"))
        cleaned = self._validator.validate_list_users_query(request.query_params)
        if org_ids is None and cleaned["organization_id"] is not None:
            org_ids = [cleaned["organization_id"]]
        key_org_ids = self.key_org_ids(request)
        qs = self._service.list_users(
            actor=request.user,
            search=cleaned["search"],
            is_superadmin=cleaned["is_superadmin"],
            org_ids=key_org_ids or org_ids,
            status_value=cleaned["status_value"],
            role_id=cleaned["role_id"],
            membership_org_ids=key_org_ids,
        )
        qs = self._apply_ordering(qs, request.query_params.get("ordering"))
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = UserResponseSerializer(page, many=True, context={"request": request})
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
            display_name=cleaned["display_name"],
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
        user = self._service.grant_superadmin(actor=request.user, target_user_id=int(pk))
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="revoke-superadmin")
    @extend_schema(**USERS_REVOKE_SUPERADMIN_POST)
    def revoke_superadmin(self, request, pk=None):
        user = self._service.revoke_superadmin(actor=request.user, target_user_id=int(pk))
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
        user = self._service.set_user_active(actor=request.user, target_user_id=int(pk), value=True)
        user = self._service.list_users(actor=request.user).get(pk=user.pk)
        return Response(UserResponseSerializer(user, context={"request": request}).data)

    @extend_schema(**USERS_DESTROY_DELETE)
    def destroy(self, request, pk=None):
        """Permanently delete a user account, or preview the deletion."""
        if self._is_truthy(request.query_params.get("dry_run")):
            report = self._service.preview_delete(actor=request.user, target_user_id=int(pk))
        else:
            report = self._service.delete_user(
                actor=request.user,
                target_user_id=int(pk),
                verification_phrase=self._hard_delete_validator.extract_verification_phrase(
                    request.data
                ),
            )
        return Response(UserDeleteReportSerializer(dataclasses.asdict(report)).data)

    @staticmethod
    def _is_truthy(raw):
        return str(raw).strip().lower() in ("true", "1") if raw is not None else False
