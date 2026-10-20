from rbac.access.org_context import OrgContextService
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from plugins.access.available_plugins import plugins_available_to
from plugins.serializers.member import AvailablePluginSerializer


class AvailablePluginsView(APIView):
    """The plugins the caller may open in the active organization (`X-Organization-Id`).

    The header is resolved like every org-scoped endpoint (missing → 400, not a member →
    403, unknown org for a SuperAdmin → 404). The list itself comes from the caller's
    membership, so a SuperAdmin who is not a member gets an empty list.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        org_id = OrgContextService().resolve(request=request)
        available = plugins_available_to(request.user, org_id)
        return Response(AvailablePluginSerializer(available, many=True).data)
