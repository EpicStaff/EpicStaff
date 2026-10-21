"""Verification of the gateway context EpicStaff signs for every request it forwards."""

import time
from collections.abc import Callable

import jwt
from pydantic import ValidationError

from epicstaff_plugin.contracts.gateway_context import (
    CONTEXT_ALGORITHM,
    CONTEXT_LEEWAY_SECONDS,
    CONTEXT_TYPE,
    GatewayContext,
)
from epicstaff_plugin.runtime.runtime_config import RuntimeConfig
from epicstaff_plugin.runtime.signing_keys import JwksFetcher, ResolvedKey, SigningKeys

MAX_CONTEXT_TOKEN_LENGTH = 8192
_REQUIRED_CLAIMS = ["iss", "aud", "iat", "exp", "jti"]


class ContextRejected(Exception):  # noqa: N818 (the platform contract names it so)
    """A request's gateway context is missing or fails a check.

    `reason` names the check: `missing`, `ambiguous`, `malformed`, `wrong_type`,
    `unknown_key`, `bad_signature`, `expired`, `not_yet_valid`, `wrong_audience`,
    `wrong_issuer`, `invalid_claims`, `request_mismatch` or `dot_segment`.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class ContextVerifier:
    """Checks a gateway context the way the platform requires, for one plugin process.

    A context passes when its signature verifies with the key its `kid` names, its `typ` is
    `epicstaff-plugin-context+jwt`, `aud` is this plugin, `iss` is the runtime file's
    issuer, it has not expired (30 s leeway), and its `request` names the method and path of
    the request it arrived with. A path with a `.` or `..` segment is refused outright.

    Keys come from the runtime file, or from a download for a key it does not list yet
    (`epicstaff_plugin.runtime.signing_keys.SigningKeys`).
    """

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        fetch_jwks: JwksFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._keys = SigningKeys(runtime, fetch_jwks=fetch_jwks, clock=clock)

    @property
    def runtime(self) -> RuntimeConfig:
        return self._keys.runtime

    @property
    def signing_keys(self) -> SigningKeys:
        """The key lookup this verifier uses; the hook check shares it."""
        return self._keys

    def verify(self, token: str, method: str, path: str) -> GatewayContext:
        """Verify `token` for a request with this method and ASGI path (`scope["path"]`).

        Blocks on the JWKS download an unknown key id may cause; inside an event loop use
        `verify_async`.

        Raises:
            ContextRejected: The context fails a check.
        """
        kid = self._preflight(token, path)
        return self._verified(token, self._keys.find_or_download(kid), method, path)

    async def verify_async(self, token: str, method: str, path: str) -> GatewayContext:
        """Like `verify`, with the JWKS download run in a worker thread.

        Raises:
            ContextRejected: The context fails a check.
        """
        kid = self._preflight(token, path)
        return self._verified(token, await self._keys.find_or_download_async(kid), method, path)

    def _preflight(self, token: str, path: str) -> str:
        if any(segment in (".", "..") for segment in path.split("/")):
            raise ContextRejected("dot_segment")
        if not token or len(token) > MAX_CONTEXT_TOKEN_LENGTH:
            raise ContextRejected("malformed")
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError:
            raise ContextRejected("malformed") from None
        if header.get("typ") != CONTEXT_TYPE:
            raise ContextRejected("wrong_type")
        if header.get("alg") != CONTEXT_ALGORITHM:
            raise ContextRejected("malformed")
        kid = header.get("kid")
        if not isinstance(kid, str):
            raise ContextRejected("malformed")
        return kid

    # One snapshot of the runtime file per verification: the key, the issuer and the plugin
    # always come from the same version of it.
    def _verified(
        self, token: str, resolved: ResolvedKey | None, method: str, path: str
    ) -> GatewayContext:
        if resolved is None:
            raise ContextRejected("unknown_key")
        document = resolved.document
        try:
            public_key = resolved.jwk.public_key()
        except ValueError:
            raise ContextRejected("unknown_key") from None
        try:
            claims = jwt.decode(
                token,
                public_key,
                algorithms=[CONTEXT_ALGORITHM],
                audience=document.plugin.identifier,
                issuer=document.issuer,
                leeway=CONTEXT_LEEWAY_SECONDS,
                options={"require": _REQUIRED_CLAIMS},
            )
        except jwt.InvalidSignatureError:
            raise ContextRejected("bad_signature") from None
        except jwt.ExpiredSignatureError:
            raise ContextRejected("expired") from None
        except jwt.ImmatureSignatureError:
            raise ContextRejected("not_yet_valid") from None
        except jwt.InvalidAudienceError:
            raise ContextRejected("wrong_audience") from None
        except jwt.InvalidIssuerError:
            raise ContextRejected("wrong_issuer") from None
        except jwt.DecodeError:
            raise ContextRejected("malformed") from None
        except jwt.InvalidTokenError:
            raise ContextRejected("invalid_claims") from None
        try:
            context = GatewayContext.model_validate(claims, extra="ignore")
        except ValidationError:
            raise ContextRejected("invalid_claims") from None
        if context.request.method != method or context.request.path != path:
            raise ContextRejected("request_mismatch")
        return context
