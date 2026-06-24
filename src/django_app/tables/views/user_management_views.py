from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from tables.serializers.user_management_serializers import (
    MembershipAssignmentRequestSerializer,
    MembershipAssignmentResponseSerializer,
    MembershipCreateRequestSerializer,
    MembershipUpdateRequestSerializer,
    OrgMemberResponseSerializer,
    UserCreateRequestSerializer,
    UserResponseSerializer,
)
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.authentication import JwtOrApiKeyAuthentication
from tables.services.rbac.permissions import HasOrgPermission, IsSuperadmin
from tables.services.rbac.user_management_service import UserManagementService
from tables.services.rbac.user_validation_service import UserValidationService


class UserPagination(PageNumberPagination):
    """Cross-org user list pagination."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class UserAdminViewSet(viewsets.ViewSet):
    """Superadmin-only management of Users.

    GET (list paginated), POST (create with optional initial org+role),
    POST {id}/grant-superadmin/, POST {id}/revoke-superadmin/.

    Domain errors raised by the service surface through the project's
    custom_exception_handler envelope; the view layer does not catch
    or translate them.
    """

    authentication_classes = [JwtOrApiKeyAuthentication]
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


class OrganizationMembershipAdminViewSet(viewsets.ViewSet):
    """Per-org membership management. Nested under
    /api/admin/organizations/{org_id}/users/...

    Authorization: superadmin globally OR a role with USERS permission
    in the org_id from the URL.
    """

    authentication_classes = [JwtOrApiKeyAuthentication]
    # Order matters: IsAuthenticated runs first so HasOrgPermission can
    # rely on request.user.is_authenticated.
    permission_classes = [IsAuthenticated, HasOrgPermission]

    # Required by HasOrgPermission. Missing this attribute raises
    # ImproperlyConfigured on first request.
    rbac_resource_type = ResourceType.USERS
    rbac_action_map = {
        "list": Permission.READ,
        "create": Permission.CREATE,
        "partial_update": Permission.UPDATE,
        "destroy": Permission.DELETE,
        "assign_users": Permission.UPDATE,
    }

    _service = UserManagementService()
    _validator = UserValidationService()

    # GET /api/admin/organizations/{org_id}/users/
    @extend_schema(
        summary="List members of an organization",
        responses={200: OrgMemberResponseSerializer(many=True)},
    )
    def list(self, request, org_id=None):
        cleaned = self._validator.validate_list_org_members_query(request.query_params)
        qs = self._service.list_org_members(
            actor=request.user,
            org_id=int(org_id),
            email=cleaned["email"],
            role_name=cleaned["role_name"],
        )
        return Response(OrgMemberResponseSerializer(qs, many=True).data)

    # POST /api/admin/organizations/{org_id}/users/
    @extend_schema(
        summary="Create user and link to organization",
        request=MembershipCreateRequestSerializer,
        responses={
            201: OrgMemberResponseSerializer,
            400: OpenApiResponse(
                description="Validation error, duplicate email, or invalid role"
            ),
            404: OpenApiResponse(description="Organization or role not found"),
        },
    )
    def create(self, request, org_id=None):
        cleaned = self._validator.validate_add_membership(request.data)
        membership = self._service.add_membership(
            actor=request.user,
            org_id=int(org_id),
            email=cleaned["email"],
            password=cleaned["password"],
            role_id=cleaned["role_id"],
        )
        return Response(
            OrgMemberResponseSerializer(membership).data,
            status=status.HTTP_201_CREATED,
        )

    # POST /api/admin/organizations/{org_id}/assign-users/
    # Routed manually via tables/urls.py — no @action decorator. drf-spectacular's
    # action discovery is router-based and misses manually-routed @action methods,
    # which causes the class docstring to leak into the operation description and
    # the request body / response schema to vanish from Swagger UI.
    @extend_schema(
        summary="Batch-assign or reassign users in an organization",
        description=(
            "Batch upsert of memberships. New (user_id, org_id) pairs are "
            "created; pre-existing pairs have their role updated (or no-op "
            "if the role is unchanged). All-or-nothing in one transaction; "
            "max 100 items; rejects duplicate user_id within the batch, "
            "self-inclusion by a non-superadmin caller "
            "(cannot_self_assign), and any change that would leave the "
            "organization with zero Org Admins (last_org_admin)."
        ),
        operation_id="rbac_assign_users",
        request=MembershipAssignmentRequestSerializer,
        examples=[
            OpenApiExample(
                "Two assignments",
                value={
                    "assignments": [
                        {"user_id": 1, "role_id": 3},
                        {"user_id": 2, "role_id": 2},
                    ]
                },
                request_only=True,
            ),
        ],
        responses={
            200: MembershipAssignmentResponseSerializer,
            400: OpenApiResponse(
                description=(
                    "Validation error, invalid role, last-Org-Admin "
                    "violation, or self-assign attempt by a non-superadmin "
                    "caller"
                )
            ),
            404: OpenApiResponse(description="Organization, role, or user not found"),
        },
    )
    def assign_users(self, request, org_id=None):
        cleaned = self._validator.validate_assign_users(request.data)
        created, updated = self._service.assign_users(
            actor=request.user,
            org_id=int(org_id),
            assignments=cleaned,
        )
        return Response(
            {
                "created": OrgMemberResponseSerializer(created, many=True).data,
                "updated": OrgMemberResponseSerializer(updated, many=True).data,
            },
            status=status.HTTP_200_OK,
        )

    # PATCH /api/admin/organizations/{org_id}/users/{user_id}/
    @extend_schema(
        summary="Change a user's role in an organization",
        request=MembershipUpdateRequestSerializer,
        responses={
            200: OrgMemberResponseSerializer,
            400: OpenApiResponse(
                description="Validation error or last Org Admin demotion"
            ),
            404: OpenApiResponse(description="Membership or role not found"),
        },
    )
    def partial_update(self, request, org_id=None, user_id=None):
        cleaned = self._validator.validate_change_role(request.data)
        membership = self._service.change_role(
            actor=request.user,
            org_id=int(org_id),
            user_id=int(user_id),
            role_id=cleaned["role_id"],
        )
        return Response(OrgMemberResponseSerializer(membership).data)

    # DELETE /api/admin/organizations/{org_id}/users/{user_id}/
    @extend_schema(
        summary="Remove user from organization",
        responses={
            204: OpenApiResponse(description="Removed"),
            400: OpenApiResponse(description="Cannot remove last Org Admin"),
            404: OpenApiResponse(description="Membership not found"),
        },
    )
    def destroy(self, request, org_id=None, user_id=None):
        self._service.remove_membership(
            actor=request.user, org_id=int(org_id), user_id=int(user_id)
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
