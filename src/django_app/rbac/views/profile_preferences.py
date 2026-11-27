from functools import cache

from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from rbac.access.gates import DenyApiKeyAuth
from rbac.access.org_context import OrgContextService
from rbac.identity.authentication import ApiKeyAuthentication, JwtAuthentication
from rbac.profile.preferences.service import UserPreferencesService
from rbac.schemas.profile_preferences import PROFILE_PREFERENCES_SECTION_PATCH


class ProfilePreferenceSectionView(APIView):
    """`PATCH /api/profile/preferences/<section>/`: the caller's own UI preferences.

    Session only: an API key has no UI to keep preferences for. Records no user action
    (listed in the user-action middleware's FALLBACK_EXCLUDED_VIEWS), because autosave
    would add an audit row for every toggle.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated, DenyApiKeyAuth]

    _service = UserPreferencesService()
    _org_context = OrgContextService()

    @extend_schema(**PROFILE_PREFERENCES_SECTION_PATCH)
    def patch(self, request, section):
        section_value = self._service.patch_section(
            request.user,
            section,
            request.data,
            cache(lambda: self._active_organization_id(request)),
        )
        return Response(section_value)

    def _active_organization_id(self, request) -> int | None:
        # Preferences belong to the user, not to an org, so the header is optional. The
        # client sends it on every request, and it may name an org the user has left or
        # one that was deactivated; only an org-keyed preference asks for it, and then it
        # is checked like anywhere else.
        if not request.headers.get("X-Organization-Id"):
            return None
        return self._org_context.resolve(request=request)
