"""OpenAPI schemas for the permission-introspection endpoints
(/api/permissions/*).

Principle-level descriptions only; detailed behavior is documented in
docs/rbac/roles_and_permissions.md.
"""

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse

from tables.serializers.permission_serializers import (
    CatalogResponseSerializer,
    MyOrgsPermissionsResponseSerializer,
    PermissionsMeResponseSerializer,
)
from tables.swagger_schemas.common_schemas import UNAUTHORIZED_401_RESPONSE

_ORG_HEADER_REQUIRED = OpenApiParameter(
    name="X-Organization-Id",
    location=OpenApiParameter.HEADER,
    type=OpenApiTypes.INT,
    required=True,
    description=(
        "Active organization id — the response is scoped to this org. "
        "Required for everyone, superadmins included (it selects which org "
        "to report on)."
    ),
)

PERMISSIONS_CATALOG_GET = dict(
    summary="Permission catalog (resource types × actions)",
    description=(
        "Static taxonomy that drives the permission-matrix UI. Caller- and "
        "org-independent; safe to cache."
    ),
    responses={
        200: CatalogResponseSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
    },
)

PERMISSIONS_ME_GET = dict(
    summary="My effective permissions in the active org",
    description=(
        "The caller's role and permissions in the org named by "
        "X-Organization-Id. `permissions` maps resource_type → action codes, "
        'or is "*" for a superadmin.'
    ),
    parameters=[_ORG_HEADER_REQUIRED],
    responses={
        200: PermissionsMeResponseSerializer,
        400: OpenApiResponse(
            description="Missing or non-integer X-Organization-Id (org_context_required)."
        ),
        401: UNAUTHORIZED_401_RESPONSE,
        403: OpenApiResponse(
            description="Caller is not a member of the org (org_membership_required)."
        ),
        404: OpenApiResponse(description="Organization not found."),
    },
)

PERMISSIONS_ME_ORGS_GET = dict(
    summary="My per-org permissions across all my orgs",
    description=(
        "The caller's permissions in every org they belong to, in one call — "
        "drives the admin nav, org filters, and per-org action gating. Takes "
        'no header. A superadmin gets {is_superadmin: true, permissions: "*"} '
        "with no `orgs` array."
    ),
    responses={
        200: MyOrgsPermissionsResponseSerializer,
        401: UNAUTHORIZED_401_RESPONSE,
    },
)
