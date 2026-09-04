from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.membership_serializers import (
    AssignableUserSerializer,
    MembershipResponseSerializer,
)
from tables.services.rbac.membership_management_service import (
    MembershipManagementService,
)
from tables.services.rbac.user_validation_service import UserValidationService
from tables.swagger_schemas.membership_schema import (
    MEMBERSHIPS_ASSIGNABLE_USERS_GET,
    MEMBERSHIPS_CREATE_POST,
    MEMBERSHIPS_DESTROY_DELETE,
    MEMBERSHIPS_LIST_GET,
    MEMBERSHIPS_UPDATE_PATCH,
)
from tables.views.cross_org_admin import CrossOrgAdminViewSet

_ORDERING_WHITELIST = {
    "email": "user__email",
    "joined_at": "joined_at",
    "role": "role__name",
    "org": "org__name",
}
_DEFAULT_ORDERING = ("org__name", "user__email")


class MembershipsPagination(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class MembershipAdminViewSet(CrossOrgAdminViewSet):
    """Flat, permission-gated cross-org membership surface.

    list:            GET    /api/admin/memberships/            (?org_ids= &search= &role_id= &status= &ordering=)
    create:          POST   /api/admin/memberships/            (org_id + email|user_id + role_id)
    partial_update:  PATCH  /api/admin/memberships/{id}/       (role_id)
    destroy:         DELETE /api/admin/memberships/{id}/

    Door gate: HasResourcePermissionAnywhere(MEMBERSHIPS); precise per-org checks
    and invariants live in MembershipManagementService.
    """

    pagination_class = MembershipsPagination
    rbac_resource_type = ResourceType.MEMBERSHIPS
    rbac_action_map = {
        "list": Permission.READ,
        "assignable_users": Permission.CREATE,
        "create": Permission.CREATE,
        "partial_update": Permission.UPDATE,
        "destroy": Permission.DELETE,
    }

    _service = MembershipManagementService()
    _validator = UserValidationService()

    @extend_schema(**MEMBERSHIPS_LIST_GET)
    def list(self, request):
        org_ids = self.parse_org_ids(request.query_params.get("org_ids"))
        filters = self._validator.validate_list_memberships_query(request.query_params)
        scopes = getattr(request, "_rbac_org_scopes", None)
        qs = self._service.list_memberships(
            actor=request.user,
            org_ids=org_ids,
            search=filters["search"],
            role_id=filters["role_id"],
            status_value=filters["status_value"],
            scopes=scopes,
        )
        qs = self._apply_ordering(qs, request.query_params.get("ordering"))
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            MembershipResponseSerializer(
                page, many=True, context={"request": request}
            ).data
        )

    @extend_schema(**MEMBERSHIPS_ASSIGNABLE_USERS_GET)
    def assignable_users(self, request):
        scopes = getattr(request, "_rbac_org_scopes", None)
        qs = self._service.list_assignable_users(
            actor=request.user,
            search=request.query_params.get("search"),
            scopes=scopes,
        )
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        return paginator.get_paginated_response(
            AssignableUserSerializer(page, many=True, context={"request": request}).data
        )

    @extend_schema(**MEMBERSHIPS_CREATE_POST)
    def create(self, request):
        cleaned = self._validator.validate_add_member(request.data)
        membership = self._service.add_member(
            actor=request.user,
            org_id=cleaned["org_id"],
            email=cleaned["email"],
            user_id=cleaned["user_id"],
            role_id=cleaned["role_id"],
        )
        return Response(
            MembershipResponseSerializer(membership, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(**MEMBERSHIPS_UPDATE_PATCH)
    def partial_update(self, request, pk=None):
        cleaned = self._validator.validate_change_role(request.data)
        membership = self._service.change_role(
            actor=request.user, membership_id=int(pk), role_id=cleaned["role_id"]
        )
        return Response(
            MembershipResponseSerializer(membership, context={"request": request}).data
        )

    @extend_schema(**MEMBERSHIPS_DESTROY_DELETE)
    def destroy(self, request, pk=None):
        self._service.remove_member(actor=request.user, membership_id=int(pk))
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _apply_ordering(self, qs, raw):
        if not raw:
            return qs.order_by(*_DEFAULT_ORDERING)
        descending = raw.startswith("-")
        key = raw.lstrip("-")
        field = _ORDERING_WHITELIST.get(key)
        if field is None:
            return qs.order_by(*_DEFAULT_ORDERING)
        primary = f"-{field}" if descending else field
        # Append a unique tiebreaker so pagination is deterministic even when
        # the chosen key (role/org/joined_at) has many ties.
        return qs.order_by(primary, "id")
