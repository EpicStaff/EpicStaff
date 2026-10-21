"""A stand-in for EpicStaff's gateway that signs contexts with a throwaway key."""

import secrets
import time
from collections.abc import Iterable, Mapping
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from epicstaff_plugin.contracts.gateway_context import (
    CONTEXT_ALGORITHM,
    CONTEXT_HEADER,
    CONTEXT_LIFETIME_SECONDS,
    CONTEXT_TYPE,
    ContextMode,
    ContextOrganization,
    ContextUser,
    GatewayContext,
    Jwk,
    Jwks,
    encode_context,
)

DEFAULT_ISSUER = "https://epicstaff.test"
DEFAULT_PLUGIN_IDENTIFIER = "sample"
DEFAULT_PLUGIN_VERSION = "0.1.0"


class ContextSigner:
    """Issues gateway contexts exactly as EpicStaff does, for tests and local runs.

    Every signer makes its own Ed25519 key. A plugin process trusts only the keys in the
    runtime file EpicStaff writes, so contexts from this signer are accepted only where a test
    put the signer's `jwks` in the runtime file (`write_runtime_file(path, signer=signer)`).
    """

    def __init__(
        self,
        *,
        plugin_identifier: str = DEFAULT_PLUGIN_IDENTIFIER,
        plugin_version: str = DEFAULT_PLUGIN_VERSION,
        issuer: str = DEFAULT_ISSUER,
    ):
        self.plugin_identifier = plugin_identifier
        self.plugin_version = plugin_version
        self.issuer = issuer
        self.kid = secrets.token_hex(8)
        self._private_key = Ed25519PrivateKey.generate()

    @property
    def jwks(self) -> Jwks:
        """The signer's public key, as EpicStaff publishes its keys."""
        return Jwks(keys=[Jwk.from_public_key(self.kid, self._private_key.public_key())])

    def context(
        self,
        method: str,
        path: str,
        *,
        mode: ContextMode = "public",
        user: ContextUser | Mapping[str, Any] | None = None,
        org: ContextOrganization | Mapping[str, Any] | None = None,
        permissions: Iterable[str] = (),
        issued_at: int | None = None,
        lifetime_seconds: int = CONTEXT_LIFETIME_SECONDS,
    ) -> GatewayContext:
        """Build the context EpicStaff would send with a request of this method and path."""
        now = int(time.time()) if issued_at is None else issued_at
        return GatewayContext.model_validate(
            {
                "iss": self.issuer,
                "aud": self.plugin_identifier,
                "iat": now,
                "exp": now + lifetime_seconds,
                "jti": secrets.token_hex(16),
                "plugin": {"identifier": self.plugin_identifier, "version": self.plugin_version},
                "org": org,
                "user": user,
                "permissions": list(permissions),
                "request": {"method": method, "path": path},
                "mode": mode,
            }
        )

    def issue(self, method: str, path: str, **context_fields: Any) -> str:
        """Return the signed context for a request; keyword arguments as for `context`."""
        return encode_context(
            self.context(method, path, **context_fields), self._private_key, self.kid
        )

    def headers(self, method: str, path: str, **context_fields: Any) -> dict[str, str]:
        """Return the request header that carries a signed context for this request."""
        return {CONTEXT_HEADER: self.issue(method, path, **context_fields)}

    def sign_claims(
        self, claims: Mapping[str, Any], *, headers: Mapping[str, Any] | None = None
    ) -> str:
        """Sign arbitrary claims with the context header, for tests of contexts that must fail.

        `headers` replaces or adds header fields (`typ`, `kid`, ...).
        """
        return jwt.encode(
            dict(claims),
            self._private_key,
            algorithm=CONTEXT_ALGORITHM,
            headers={"typ": CONTEXT_TYPE, "kid": self.kid, **(headers or {})},
        )
