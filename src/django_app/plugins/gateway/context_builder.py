import secrets
import time

from epicstaff_plugin.contracts.gateway_context import (
    CONTEXT_LIFETIME_SECONDS,
    ContextRequest,
    GatewayContext,
    PluginIdentity,
    encode_context,
)

from plugins.identity.signing_keys import cached_signing_key

PUBLIC_MODE = "public"


def public_context(issuer: str, identifier: str, version: str, method: str, path: str) -> str:
    """Sign the context of a request to a public path: no user, no organization, no permissions.

    It is bound to the request's method and canonical path (the plugin checks both) and
    lives 60 s.
    """
    issued_at = int(time.time())
    context = GatewayContext(
        iss=issuer,
        aud=identifier,
        iat=issued_at,
        exp=issued_at + CONTEXT_LIFETIME_SECONDS,
        jti=secrets.token_hex(16),
        plugin=PluginIdentity(identifier=identifier, version=version),
        org=None,
        user=None,
        permissions=[],
        request=ContextRequest(method=method, path=path),
        mode=PUBLIC_MODE,
    )
    key = cached_signing_key.get()
    return encode_context(context, key.private_key, key.kid)
