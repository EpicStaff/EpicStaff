from tables.models.crew_models import (
    DefaultAgentConfig,
    DefaultCrewConfig,
    DefaultToolConfig,
)
from tables.models.default_models import DefaultModels

from drf_spectacular.utils import extend_schema, OpenApiResponse
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.shortcuts import get_object_or_404

from tables.services.rbac.permissions import IsSuperadminOrReadOnly

from tables.models.realtime_models import DefaultRealtimeAgentConfig
from tables.serializers.default_config_serializers import (
    DefaultConfigSerializer,
    DefaultCrewConfigSerializer,
    DefaultAgentConfigSerializer,
    DefaultRealtimeAgentConfigSerializer,
    DefaultToolConfigSerializer,
    DefaultModelsSerializer,
)
from tables.swagger_schemas.default_config_schemas import (
    DEFAULT_AGENT_CONFIG_GET,
    DEFAULT_AGENT_CONFIG_PUT,
    DEFAULT_CONFIG_GET,
    DEFAULT_CREW_CONFIG_GET,
    DEFAULT_CREW_CONFIG_PUT,
    DEFAULT_MODELS_GET,
    DEFAULT_MODELS_PUT,
    DEFAULT_REALTIME_CONFIG_GET,
    DEFAULT_REALTIME_CONFIG_PUT,
    DEFAULT_TOOL_CONFIG_GET,
    DEFAULT_TOOL_CONFIG_PUT,
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


class DefaultConfigAPIView(APIView):
    @extend_schema(**DEFAULT_CONFIG_GET)
    def get(self, request, *args, **kwargs):
        data = {
            "default_agent_config": DefaultAgentConfigSerializer(
                DefaultAgentConfig.load()
            ).data,
            "default_realtime_agent_config": DefaultRealtimeAgentConfigSerializer(
                DefaultRealtimeAgentConfig.load()
            ).data,
            "default_crew_config": DefaultCrewConfigSerializer(
                DefaultCrewConfig.load()
            ).data,
            "default_tool_config": DefaultToolConfigSerializer(
                DefaultToolConfig.load()
            ).data,
        }
        serializer = DefaultConfigSerializer(data)
        return Response(serializer.data)


class DefaultRealtimeAgentConfigAPIView(BaseDefaultConfigAPIView):
    model = DefaultRealtimeAgentConfig
    serializer = DefaultRealtimeAgentConfigSerializer

    @extend_schema(**DEFAULT_REALTIME_CONFIG_GET)
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(**DEFAULT_REALTIME_CONFIG_PUT)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class DefaultAgentConfigAPIView(BaseDefaultConfigAPIView):
    model = DefaultAgentConfig
    serializer = DefaultAgentConfigSerializer

    @extend_schema(**DEFAULT_AGENT_CONFIG_GET)
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(**DEFAULT_AGENT_CONFIG_PUT)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class DefaultCrewConfigAPIView(BaseDefaultConfigAPIView):
    model = DefaultCrewConfig
    serializer = DefaultCrewConfigSerializer

    @extend_schema(**DEFAULT_CREW_CONFIG_GET)
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(**DEFAULT_CREW_CONFIG_PUT)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


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


class DefaultToolConfigAPIView(BaseDefaultConfigAPIView):
    model = DefaultToolConfig
    serializer = DefaultToolConfigSerializer

    @extend_schema(**DEFAULT_TOOL_CONFIG_GET)
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(**DEFAULT_TOOL_CONFIG_PUT)
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)
