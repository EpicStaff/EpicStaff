from datetime import datetime, timedelta, timezone

import jwt
from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from tables.models.rbac_models import OrganizationConfig
from tables.models.rbac_models.rbac_enums import Permission, ResourceType
from tables.services.rbac.authentication import ApiKeyAuthentication, JwtAuthentication
from tables.services.rbac.org_context_service import OrgContextService
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.swagger_schemas.audit_schemas import AUDIT_TOKEN_CREATE


class AuditTokenView(APIView):
    """
    POST /api/audit/token/ — mints a short-lived JWT for the caller's
    active organization, consumed directly by `auditor` (the frontend
    never talks to Django again for audit reads/exports after this one
    call). `auditor` verifies locally with the same JWT_SECRET - no
    callback to Django per request.
    """

    authentication_classes = [JwtAuthentication, ApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    _org_context = OrgContextService()
    _resolver = PermissionResolver()

    @extend_schema(**AUDIT_TOKEN_CREATE)
    def post(self, request):
        org_id = self._org_context.resolve(request=request, view_kwargs={})
        effective = self._resolver.resolve(user=request.user, org_id=org_id)

        actions = []
        if effective.can(ResourceType.AUDIT, Permission.READ):
            actions.append("read")
        if effective.can(ResourceType.AUDIT, Permission.EXPORT):
            actions.append("export")

        if not actions:
            return Response(
                {"detail": "You do not have AUDIT permissions in this organization."},
                status=status.HTTP_403_FORBIDDEN,
            )

        # audit_retention_days lives on OrganizationConfig (1:1), not Organization
        # directly. create_organization() always creates this row atomically and
        # migration 0210 backfilled every pre-existing org, so this should never
        # miss in practice - but this is a read-only view (no get_or_create side
        # effect belongs here just to mint a token), so fall back to the same
        # default (0 = unlimited) the field itself defaults to, rather than 500ing.
        try:
            retention_days = OrganizationConfig.objects.get(
                org_id=org_id
            ).audit_retention_days
        except OrganizationConfig.DoesNotExist:
            retention_days = 0

        now = datetime.now(timezone.utc)
        payload = {
            "org_id": org_id,
            "actions": actions,
            "retention_days": retention_days,
            "iat": now,
            "exp": now + timedelta(seconds=settings.AUDIT_TOKEN_TTL_SECONDS),
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm="HS256")

        return Response(
            {"token": token, "expires_in": settings.AUDIT_TOKEN_TTL_SECONDS}
        )
