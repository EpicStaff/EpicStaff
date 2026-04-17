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

from tables.models.realtime_models import DefaultRealtimeAgentConfig
from tables.serializers.default_config_serializers import (
    DefaultConfigSerializer,
    DefaultCrewConfigSerializer,
    DefaultAgentConfigSerializer,
    DefaultRealtimeAgentConfigSerializer,
    DefaultToolConfigSerializer,
    DefaultModelsSerializer,
)


class BaseDefaultConfigAPIView(APIView):
    """A Base model for all default config api views."""

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
    @extend_schema(
        summary="Get default config",
        responses={
            200: DefaultConfigSerializer,
            404: OpenApiResponse(description="Not found"),
        },
    )
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

    @extend_schema(
        summary="Get default realtime config",
        responses={
            200: DefaultRealtimeAgentConfigSerializer,
            404: OpenApiResponse(description="Not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Update default realtime config",
        request=DefaultRealtimeAgentConfigSerializer,
        responses={
            200: DefaultRealtimeAgentConfigSerializer,
            404: OpenApiResponse(description="Not found"),
            400: OpenApiResponse(description="Validation Error"),
        },
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class DefaultAgentConfigAPIView(BaseDefaultConfigAPIView):
    model = DefaultAgentConfig
    serializer = DefaultAgentConfigSerializer

    @extend_schema(
        summary="Get default agent config",
        responses={
            200: DefaultAgentConfigSerializer,
            404: OpenApiResponse(description="Not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Update default agent config",
        request=DefaultAgentConfigSerializer,
        responses={
            200: DefaultAgentConfigSerializer,
            404: OpenApiResponse(description="Not found"),
            400: OpenApiResponse(description="Validation Error"),
        },
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class DefaultCrewConfigAPIView(BaseDefaultConfigAPIView):
    model = DefaultCrewConfig
    serializer = DefaultCrewConfigSerializer

    @extend_schema(
        summary="Get default crew config",
        responses={
            200: DefaultCrewConfigSerializer,
            404: OpenApiResponse(description="Not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Update default crew config",
        request=DefaultCrewConfigSerializer,
        responses={
            200: DefaultCrewConfigSerializer,
            404: OpenApiResponse(description="Not found"),
            400: OpenApiResponse(description="Validation Error"),
        },
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class DefaultModelsAPIView(BaseDefaultConfigAPIView):
    model = DefaultModels
    serializer = DefaultModelsSerializer

    def get_object(self):
        return DefaultModels.load()

    @extend_schema(
        summary="Get default models",
        responses={
            200: DefaultModelsSerializer,
            404: OpenApiResponse(description="Not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Set default models",
        request=DefaultModelsSerializer,
        responses={
            200: DefaultModelsSerializer,
            404: OpenApiResponse(description="Not found"),
            400: OpenApiResponse(description="Validation Error"),
        },
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)


class DefaultToolConfigAPIView(BaseDefaultConfigAPIView):
    model = DefaultToolConfig
    serializer = DefaultToolConfigSerializer

    @extend_schema(
        summary="Get default tool config",
        responses={
            200: DefaultToolConfigSerializer,
            404: OpenApiResponse(description="Not found"),
        },
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary="Update default tool config",
        request=DefaultToolConfigSerializer,
        responses={
            200: DefaultToolConfigSerializer,
            404: OpenApiResponse(description="Not found"),
            400: OpenApiResponse(description="Validation Error"),
        },
    )
    def put(self, request, *args, **kwargs):
        return super().put(request, *args, **kwargs)
