from django.conf import settings
from drf_spectacular.utils import extend_schema
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from tables.import_export.constants import IMPORT_VERSION
from tables.serializers.system_info_serializers import SystemInfoSerializer
from tables.swagger_schemas.system_info_schemas import SYSTEM_INFO_GET


def _empty_to_none(value: str) -> str | None:
    return value or None


class SystemInfoView(APIView):
    """GET /api/system-info/ — build identity and feature switches.

    Describes the whole installation, so it is deliberately not org-scoped and has no
    role gate. It returns only the documented keys, never other settings.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    @extend_schema(**SYSTEM_INFO_GET)
    def get(self, request):
        payload = {
            "version": _empty_to_none(settings.EPICSTAFF_VERSION),
            "git_ref": _empty_to_none(settings.EPICSTAFF_GIT_REF),
            "git_sha": _empty_to_none(settings.EPICSTAFF_GIT_SHA),
            "commit_date": _empty_to_none(settings.EPICSTAFF_COMMIT_DATE),
            "import_version": IMPORT_VERSION,
            "features": {
                "chats": settings.CHAT_ENABLED,
                "plugins": settings.PLUGINS_ENABLED,
                "session_audit": settings.SESSION_AUDIT_TRAIL_ENABLED,
                "user_audit": settings.USER_AUDIT_TRAIL_ENABLED,
            },
        }
        response = Response(SystemInfoSerializer(payload).data)
        response["Cache-Control"] = "private, no-store"
        return response
