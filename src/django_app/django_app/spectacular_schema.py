from drf_spectacular.openapi import AutoSchema
from drf_spectacular.plumbing import ResolvedComponent
from rbac.identity.authentication import BearerAuthScheme

ORG_HEADER_SCHEME = "OrganizationId"

# An apiKey scheme is the only OpenAPI way to let Swagger UI's Authorize send the header.
_ORG_HEADER_SECURITY_SCHEME = {
    "type": "apiKey",
    "in": "header",
    "name": "X-Organization-Id",
    "description": (
        "Integer id of the active organization. A user session (BearerAuth) must send it "
        "to every endpoint that acts in one organization, e.g. /api/permissions/me/; "
        "the operations listing it together with BearerAuth are those endpoints. "
        "A personal API key ignores it and acts in its own organization. "
        "Click Authorize and enter the id; Swagger sends it wherever it is listed."
    ),
}


class OrganizationContextAutoSchema(AutoSchema):
    """Documents `X-Organization-Id` on the operations whose view acts in the active org.

    A view declares `uses_organization_context = False` when no request it serves depends on
    the active org; an `@action(uses_organization_context=False)` opts out one action of a
    view inheriting `OrgScopedResolverMixin`. Undeclared counts as True, since most
    endpoints act in the active org.

    The header joins each credential that needs it in one requirement (AND), so the
    schema never claims the header alone authenticates. The scheme component is
    registered here, where it is referenced, as drf-spectacular does for auth schemes.
    """

    def get_auth(self):
        requirements = super().get_auth()
        if not getattr(self.view, "uses_organization_context", True):
            return requirements
        # Only a user session acts in the org named by the header. A plugin key acts in
        # its grant's org; a USER API key in its own org whatever the header says.
        # ApiKeyAuth stays without it although the system key, which shares that scheme,
        # does need the header: the system key is for internal services only.
        with_header = [
            {**requirement, ORG_HEADER_SCHEME: []}
            if BearerAuthScheme.name in requirement
            else requirement
            for requirement in requirements
        ]
        if with_header != requirements:
            self.registry.register_on_missing(
                ResolvedComponent(
                    name=ORG_HEADER_SCHEME,
                    type=ResolvedComponent.SECURITY_SCHEMA,
                    object=ORG_HEADER_SCHEME,
                    schema=_ORG_HEADER_SECURITY_SCHEME,
                )
            )
        return with_header
