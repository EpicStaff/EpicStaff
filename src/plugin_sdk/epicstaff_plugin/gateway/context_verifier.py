"""Verification of the gateway context EpicStaff signs for every request it forwards."""

import asyncio
import http.client
import logging
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

import jwt
from pydantic import ValidationError

from epicstaff_plugin.contracts.gateway_context import (
    CONTEXT_ALGORITHM,
    CONTEXT_LEEWAY_SECONDS,
    CONTEXT_TYPE,
    GatewayContext,
    Jwk,
    Jwks,
)
from epicstaff_plugin.contracts.runtime import RuntimeFile
from epicstaff_plugin.runtime.runtime_config import RuntimeConfig

logger = logging.getLogger(__name__)

# An unknown key id is answered by one JWKS download at most this often, so a stream of
# forged tokens cannot turn the plugin into a load generator against EpicStaff.
JWKS_REFETCH_INTERVAL_SECONDS = 30
# A downloaded key only bridges the gap until the node rewrites the runtime file with it.
FETCHED_KEYS_MAX_AGE_SECONDS = 600
JWKS_FETCH_TIMEOUT_SECONDS = 2
JWKS_API_PATH = "plugin-public/jwks/"
MAX_JWKS_BYTES = 64 * 1024
MAX_CONTEXT_TOKEN_LENGTH = 8192
_REQUIRED_CLAIMS = ["iss", "aud", "iat", "exp", "jti"]

JwksFetcher = Callable[[str], bytes]


class ContextRejected(Exception):  # noqa: N818 (the platform contract names it so)
    """A request's gateway context is missing or fails a check.

    `reason` names the check: `missing`, `ambiguous`, `malformed`, `wrong_type`,
    `unknown_key`, `bad_signature`, `expired`, `not_yet_valid`, `wrong_audience`,
    `wrong_issuer`, `invalid_claims`, `request_mismatch` or `dot_segment`.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class _FetchedKeys:
    jwks: Jwks
    fetched_at: float
    runtime_document: RuntimeFile


class ContextVerifier:
    """Checks a gateway context the way the platform requires, for one plugin process.

    A context passes when its signature verifies with the key its `kid` names, its `typ` is
    `epicstaff-plugin-context+jwt`, `aud` is this plugin, `iss` is the runtime file's
    issuer, it has not expired (30 s leeway), and its `request` names the method and path of
    the request it arrived with. A path with a `.` or `..` segment is refused outright.

    Keys come from the runtime file. An unknown `kid` (EpicStaff rotated its key and the node
    has not rewritten the file yet) re-reads the file and then downloads EpicStaff's JWKS, at
    most once per 30 s; downloaded keys are dropped once the runtime file changes or after
    10 minutes, so a retired key does not stay trusted.
    """

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        fetch_jwks: JwksFetcher | None = None,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._runtime = runtime
        self._fetch_jwks = fetch_jwks or _fetch_jwks_over_http
        self._clock = clock
        self._refresh_lock = threading.Lock()
        self._last_fetch_at: float | None = None
        self._fetched: _FetchedKeys | None = None

    @property
    def runtime(self) -> RuntimeConfig:
        return self._runtime

    def verify(self, token: str, method: str, path: str) -> GatewayContext:
        """Verify `token` for a request with this method and ASGI path (`scope["path"]`).

        Blocks on the JWKS download an unknown key id may cause; inside an event loop use
        `verify_async`.

        Raises:
            ContextRejected: The context fails a check.
        """
        kid = self._preflight(token, path)
        document = self._runtime.document
        key = self._key(kid, document)
        if key is None:
            self._refresh_keys()
            document = self._runtime.document
            key = self._known_key(kid, document)
        return self._verified(token, key, document, method, path)

    async def verify_async(self, token: str, method: str, path: str) -> GatewayContext:
        """Like `verify`, with the JWKS download run in a worker thread.

        Raises:
            ContextRejected: The context fails a check.
        """
        kid = self._preflight(token, path)
        document = self._runtime.document
        key = self._key(kid, document)
        if key is None:
            await asyncio.to_thread(self._refresh_keys)
            document = self._runtime.document
            key = self._known_key(kid, document)
        return self._verified(token, key, document, method, path)

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
    def _key(self, kid: str, document: RuntimeFile) -> Jwk | None:
        if key := document.jwks.find(kid):
            return key
        fetched = self._fetched
        if (
            fetched is not None
            and fetched.runtime_document is document
            and self._clock() - fetched.fetched_at < FETCHED_KEYS_MAX_AGE_SECONDS
        ):
            return fetched.jwks.find(kid)
        return None

    def _known_key(self, kid: str, document: RuntimeFile) -> Jwk:
        key = self._key(kid, document)
        if key is None:
            raise ContextRejected("unknown_key")
        return key

    def _refresh_keys(self) -> None:
        with self._refresh_lock:
            now = self._clock()
            if (
                self._last_fetch_at is not None
                and now - self._last_fetch_at < JWKS_REFETCH_INTERVAL_SECONDS
            ):
                return
            self._last_fetch_at = now
            # Read first: the node may have rewritten the file with the new key already.
            document = self._runtime.document
            url = document.epicstaff_api_url.rstrip("/") + "/" + JWKS_API_PATH
            try:
                jwks = Jwks.model_validate_json(self._fetch_jwks(url), extra="ignore")
            except (OSError, http.client.HTTPException, ValueError) as error:
                # ValidationError is a ValueError: a wrong document counts as a failed download.
                logger.warning(
                    "Could not download EpicStaff's signing keys from %s: %s", url, error
                )
                return
            self._fetched = _FetchedKeys(jwks=jwks, fetched_at=now, runtime_document=document)

    def _verified(
        self, token: str, key: Jwk, document: RuntimeFile, method: str, path: str
    ) -> GatewayContext:
        try:
            public_key = key.public_key()
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


def _fetch_jwks_over_http(url: str) -> bytes:
    # No proxy: the internal API is reached directly on the plugins network, never through
    # an egress proxy the environment may name.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with opener.open(request, timeout=JWKS_FETCH_TIMEOUT_SECONDS) as response:
        body = response.read(MAX_JWKS_BYTES + 1)
    if len(body) > MAX_JWKS_BYTES:
        raise ValueError(f"the JWKS is larger than {MAX_JWKS_BYTES} bytes")
    return body
