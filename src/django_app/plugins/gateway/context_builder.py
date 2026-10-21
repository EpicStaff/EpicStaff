import secrets
import time

from epicstaff_plugin.contracts.gateway_context import (
    CONTEXT_LIFETIME_SECONDS,
    ContextOrganization,
    ContextRequest,
    ContextUser,
    GatewayContext,
    PluginIdentity,
    encode_context,
)

from plugins.identity.signing_keys import cached_signing_key

PUBLIC_MODE = "public"
USER_MODE = "user"


def public_context(issuer: str, identifier: str, version: str, method: str, path: str) -> str:
    """Sign the context of a request to a public path: no user, no organization, no permissions.

    It is bound to the request's method and canonical path (the plugin checks both) and
    lives 60 s.
    """
    return _signed(issuer, identifier, version, method, path, mode=PUBLIC_MODE)


def user_context(
    issuer: str,
    identifier: str,
    version: str,
    method: str,
    path: str,
    *,
    organization: ContextOrganization,
    user: ContextUser,
    permissions: list[str],
) -> str:
    """Sign the context of a logged-in person's request in `organization`.

    `permissions` are the person's actions on the plugin there, in manifest order; they always
    include `read`, as the gateway forwards nothing else. Bound to the request like a public
    context, and lives 60 s.
    """
    return _signed(
        issuer,
        identifier,
        version,
        method,
        path,
        mode=USER_MODE,
        organization=organization,
        user=user,
        permissions=permissions,
    )


def _signed(
    issuer: str,
    identifier: str,
    version: str,
    method: str,
    path: str,
    *,
    mode: str,
    organization: ContextOrganization | None = None,
    user: ContextUser | None = None,
    permissions: list[str] | None = None,
) -> str:
    issued_at = int(time.time())
    context = GatewayContext(
        iss=issuer,
        aud=identifier,
        iat=issued_at,
        exp=issued_at + CONTEXT_LIFETIME_SECONDS,
        jti=secrets.token_hex(16),
        plugin=PluginIdentity(identifier=identifier, version=version),
        org=organization,
        user=user,
        permissions=permissions or [],
        request=ContextRequest(method=method, path=path),
        mode=mode,
    )
    key = cached_signing_key.get()
    return encode_context(context, key.private_key, key.kid)
