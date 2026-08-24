from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.serializers.api_key_serializers import (
    ApiKeyAdminSerializer,
    ApiKeySerializer,
)
from tables.swagger_schemas.api_key_schema import (
    API_KEYS_MANAGEMENT_DELETE,
    API_KEYS_MANAGEMENT_LIST,
    API_KEYS_MANAGEMENT_REVOKE_POST,
    PROFILE_API_KEY_DELETE,
    PROFILE_API_KEY_REVOKE_POST,
    PROFILE_API_KEYS_GET,
    PROFILE_API_KEYS_POST,
)
from tables.services.rbac.api_key.admin_service import (
    ALLOWED_STATUS_FILTERS,
    ApiKeyAdminService,
)
from tables.services.rbac.api_key.service import ApiKeyService
from tables.services.rbac.api_key.validation import ApiKeyValidationService
from tables.services.rbac.authentication import (
    ApiKeyAuthentication,
    JwtAuthentication,
)
from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permissions import DenyApiKeyAuth, HasOrgPermission
from tables.services.rbac.rbac_exceptions import FormValidationError


class ProfileApiKeysView(APIView):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, DenyApiKeyAuth]

    _service = ApiKeyService()
    _validator = ApiKeyValidationService()

    @extend_schema(**PROFILE_API_KEYS_GET)
    def get(self, request):
        keys = self._service.list_keys(request.user)
        return Response(ApiKeySerializer(keys, many=True).data)

    @extend_schema(**PROFILE_API_KEYS_POST)
    def post(self, request):
        cleaned = self._validator.validate_create(request.data)
        issued = self._service.create_key(
            user=request.user,
            name=cleaned["name"],
            expires_in_days=cleaned["expires_in_days"],
        )
        payload = ApiKeySerializer(issued.api_key).data
        payload["api_key"] = issued.raw_key
        return Response(payload, status=status.HTTP_201_CREATED)


class ProfileApiKeyDetailView(APIView):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, DenyApiKeyAuth]

    _service = ApiKeyService()

    @extend_schema(**PROFILE_API_KEY_DELETE)
    def delete(self, request, key_id):
        self._service.delete_key(user=request.user, key_id=key_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProfileApiKeyRevokeView(APIView):
    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, DenyApiKeyAuth]

    _service = ApiKeyService()

    @extend_schema(**PROFILE_API_KEY_REVOKE_POST)
    def post(self, request, key_id):
        key = self._service.revoke_key(user=request.user, key_id=key_id)
        return Response(ApiKeySerializer(key).data)


class ApiKeyManagementViewSet(viewsets.ViewSet):
    """Org-scoped API key management, gated by SECRETS permissions.

    HasOrgPermission resolves the active org and checks the caller's
    SECRETS bits; superadmins bypass and may omit X-Organization-Id to see
    every org's keys.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, DenyApiKeyAuth, HasOrgPermission]
    rbac_resource_type = ResourceType.SECRETS
    rbac_action_map = {
        "list": Permission.READ,
        "revoke": Permission.UPDATE,
        "destroy": Permission.DELETE,
    }

    _service = ApiKeyAdminService()
    _org_context = OrgContextService()

    @extend_schema(**API_KEYS_MANAGEMENT_LIST)
    def list(self, request):
        status_value = request.query_params.get("status")
        if status_value is not None and status_value not in ALLOWED_STATUS_FILTERS:
            raise FormValidationError(
                [
                    {
                        "field": "status",
                        "value": status_value,
                        "reason": f"Must be one of {', '.join(ALLOWED_STATUS_FILTERS)}.",
                    }
                ]
            )
        owner_param = request.query_params.get("user")
        owner_id = None
        if owner_param is not None:
            try:
                owner_id = int(owner_param)
            except (TypeError, ValueError):
                raise FormValidationError(
                    [
                        {
                            "field": "user",
                            "value": owner_param,
                            "reason": "Must be an integer user id.",
                        }
                    ]
                )
        keys = self._service.list_keys(
            org_id=self._resolve_org_id(request),
            owner_id=owner_id,
            status_value=status_value,
            search=request.query_params.get("search"),
        )
        return Response(
            ApiKeyAdminSerializer(keys, many=True, context={"request": request}).data
        )

    @extend_schema(**API_KEYS_MANAGEMENT_REVOKE_POST)
    def revoke(self, request, pk=None):
        key = self._service.revoke_key(org_id=self._resolve_org_id(request), key_id=pk)
        return Response(
            ApiKeyAdminSerializer(key, context={"request": request}).data
        )

    @extend_schema(**API_KEYS_MANAGEMENT_DELETE)
    def destroy(self, request, pk=None):
        self._service.delete_key(org_id=self._resolve_org_id(request), key_id=pk)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _resolve_org_id(self, request):
        # Superadmin without a header → cross-org view (no org filter).
        # Everyone else already passed HasOrgPermission, so the header
        # resolves to a validated membership.
        if getattr(request.user, "is_superadmin", False) and not request.headers.get(
            "X-Organization-Id"
        ):
            return None
        return self._org_context.resolve(request=request, view_kwargs=None)
