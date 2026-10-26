"""EpicStaff's public signing keys as a plugin process knows them.

EpicStaff signs gateway contexts and hook assertions with one Ed25519 key. Both verifiers find
the key a token's `kid` names here, so they follow one rule for keys the runtime file does not
list yet, and share one download budget.
"""

import asyncio
import http.client
import logging
import threading
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from epicstaff_plugin.contracts.gateway_context import Jwk, Jwks
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

JwksFetcher = Callable[[str], bytes]


@dataclass(frozen=True)
class ResolvedKey:
    """A signing key, with the version of the runtime file it was found through.

    A verifier takes the issuer and the plugin from `document` too, so the key and the claims
    it checks always come from one version of the file.
    """

    jwk: Jwk
    document: RuntimeFile


@dataclass(frozen=True)
class _FetchedKeys:
    jwks: Jwks
    fetched_at: float
    runtime_document: RuntimeFile


class SigningKeys:
    """Finds EpicStaff's public key for a `kid`: from the runtime file, else from a download.

    An unknown `kid` (EpicStaff rotated its key and the node has not rewritten the file yet)
    re-reads the file and then downloads EpicStaff's JWKS, at most once per 30 s; downloaded
    keys are dropped once the runtime file changes or after 10 minutes, so a retired key does
    not stay trusted.
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

    def find(self, kid: str) -> ResolvedKey | None:
        """Return the key `kid` names if it is already known, without downloading anything."""
        document = self._runtime.document
        if key := document.jwks.find(kid):
            return ResolvedKey(key, document)
        fetched = self._fetched
        if (
            fetched is not None
            and fetched.runtime_document is document
            and self._clock() - fetched.fetched_at < FETCHED_KEYS_MAX_AGE_SECONDS
            and (key := fetched.jwks.find(kid))
        ):
            return ResolvedKey(key, document)
        return None

    def find_or_download(self, kid: str) -> ResolvedKey | None:
        """Return the key `kid` names, downloading the JWKS when it is unknown (blocking)."""
        resolved = self.find(kid)
        if resolved is None:
            self._refresh()
            resolved = self.find(kid)
        return resolved

    async def find_or_download_async(self, kid: str) -> ResolvedKey | None:
        """Like `find_or_download`, with the download run in a worker thread."""
        resolved = self.find(kid)
        if resolved is None:
            await asyncio.to_thread(self._refresh)
            resolved = self.find(kid)
        return resolved

    def _refresh(self) -> None:
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
