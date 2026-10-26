from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.access.plugin_access import eligible_organizations, loginable_plugin
from plugins.serializers.login import PluginLoginOrganizationsSerializer


class PluginLoginOrganizationsView(APIView):
    """`GET /api/plugins/{identifier}/login-organizations/`: where the caller may open a plugin.

    For EpicStaff's organization chooser during a plugin login. The list is the caller's own
    memberships that the plugin may be used in (`plugin_access`), sorted by name; it never
    names an organization the caller is not a member of, and `X-Organization-Id` plays no part.
    A SuperAdmin who is a member nowhere, and the system API key, get an empty list. The
    authentication classes are pinned so no other credential can ever authenticate here.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, identifier: str):
        plugin = loginable_plugin(identifier)
        organizations = eligible_organizations(request.user, plugin)
        return Response(
            PluginLoginOrganizationsSerializer(
                {"plugin": plugin, "organizations": organizations}
            ).data
        )
