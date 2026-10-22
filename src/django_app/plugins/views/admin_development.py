"""SuperAdmin control of plugin development mode for one plugin: its target and runtime file.

Deployment-wide and JWT only, like the rest of /api/admin/plugins/. Nothing here routes or
issues anything while `PLUGINS_DEV_MODE` is off, except stopping development, which only
removes state.
"""

from functools import partial

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.development.development_runtime import DevelopmentRuntimeFileService
from plugins.development.development_targets import (
    DevelopmentPortRules,
    DevelopmentPorts,
    DevelopmentTargetService,
)
from plugins.exceptions import InvalidDevelopmentPortsError
from plugins.serializers.development import (
    PluginDevelopmentSerializer,
    PluginDevelopmentUpdateSerializer,
)
from plugins.views.admin_plugins import ADMIN_AUTHENTICATION, ADMIN_PERMISSIONS


class PluginDevelopmentView(APIView):
    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS
    _service = DevelopmentTargetService()

    @extend_schema(responses=PluginDevelopmentSerializer)
    def get(self, request, identifier: str):
        return Response(PluginDevelopmentSerializer(self._service.state_of(identifier)).data)

    @extend_schema(request=PluginDevelopmentUpdateSerializer, responses=PluginDevelopmentSerializer)
    def put(self, request, identifier: str):
        state = self._service.set_ports(
            identifier, partial(_validated_ports, request.data), request.user
        )
        return Response(PluginDevelopmentSerializer(state).data)

    @extend_schema(responses={204: None})
    def delete(self, request, identifier: str):
        """Stop development: the plugin is served from its package again, and its development
        keys stop working."""
        self._service.clear(identifier, request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _validated_ports(data, rules: DevelopmentPortRules) -> DevelopmentPorts:
    body = PluginDevelopmentUpdateSerializer(
        data=data,
        context={
            "api_port": rules.api_port,
            "can_use_backend": rules.can_use_backend,
            "can_use_spa": rules.can_use_spa,
        },
    )
    if not body.is_valid():
        raise InvalidDevelopmentPortsError(body.problems())
    return DevelopmentPorts(**body.validated_data)


class PluginDevelopmentRuntimeFileView(APIView):
    """Download the plugin's development runtime file; every earlier one's keys stop at once.

    The body holds keys and the plugin's secret settings: it is sent once, never stored, and
    marked so that no cache keeps it.
    """

    authentication_classes = ADMIN_AUTHENTICATION
    permission_classes = ADMIN_PERMISSIONS

    @extend_schema(request=None, responses={200: OpenApiTypes.OBJECT})
    def post(self, request, identifier: str):
        document = DevelopmentRuntimeFileService().issue(identifier, request.user)
        response = Response(document)
        response["Cache-Control"] = "no-store"
        response["Content-Disposition"] = (
            f'attachment; filename="{identifier}-development-runtime.json"'
        )
        return response
