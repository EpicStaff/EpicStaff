from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tables.serializers.api_key_serializers import ApiKeySerializer
from tables.swagger_schemas.api_key_schema import (
    PROFILE_API_KEY_DELETE,
    PROFILE_API_KEY_REVOKE_POST,
    PROFILE_API_KEYS_GET,
    PROFILE_API_KEYS_POST,
)
from tables.services.rbac.api_key.service import ApiKeyService
from tables.services.rbac.api_key.validation import ApiKeyValidationService
from tables.services.rbac.authentication import (
    ApiKeyAuthentication,
    JwtAuthentication,
)
from tables.services.rbac.permissions import DenyApiKeyAuth


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
