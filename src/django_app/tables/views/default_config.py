from tables.models.default_models import DefaultModels

from drf_spectacular.utils import extend_schema
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from tables.services.rbac.permissions import IsSuperadminOrReadOnly

from tables.serializers.default_config_serializers import (
    DefaultModelsSerializer,
)
from tables.swagger_schemas.default_config_schemas import (
    DEFAULT_MODELS_GET,
    DEFAULT_MODELS_PUT,
)


class BaseDefaultConfigAPIView(APIView):
    """A Base model for all default config api views.

    These are global install-wide default singletons: any authenticated user
    may read them; only a superadmin may modify them (write-lockdown).
    """

    permission_classes = [IsSuperadminOrReadOnly]
    model = None
    serializer = None

    def get_object(self):
        return get_object_or_404(self.model, pk=1)

    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        serializer = self.serializer(obj, many=False)
        return Response(serializer.data)

    def put(self, request, *args, **kwargs):
        obj = self.get_object()
        serializer = self.serializer(obj, data=request.data)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class DefaultModelsAPIView(BaseDefaultConfigAPIView):
    model = DefaultModels
    serializer = DefaultModelsSerializer

    def get_object(self):
        return DefaultModels.load()

    @extend_schema(**DEFAULT_MODELS_GET)
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(**DEFAULT_MODELS_PUT)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)
