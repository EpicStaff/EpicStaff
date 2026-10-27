"""A stand-in for EpicStaff's hook calls, signed with a `ContextSigner`'s throwaway key."""

import secrets
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from epicstaff_plugin.contracts.gateway_context import ContextOrganization
from epicstaff_plugin.contracts.hook_api import (
    HOOK_ASSERTION_GRACE_SECONDS,
    HOOK_ASSERTION_TYPE,
    HOOK_HEADER,
    HOOK_PATHS,
    HOOK_REQUEST_FORMAT,
    HookAssertionClaims,
    HookKind,
    HookRequest,
    encode_hook_body,
    hook_body_sha256,
)
from epicstaff_plugin.contracts.manifest import MAX_HOOK_TIMEOUT_SECONDS
from epicstaff_plugin.testing.context_signer import DEFAULT_ORGANIZATION, ContextSigner


@dataclass(frozen=True)
class HookCall:
    """One hook call as the node sends it: `POST <path>` with these headers and body bytes."""

    path: str
    headers: dict[str, str]
    body: bytes
    request: HookRequest
    claims: HookAssertionClaims


class HookSigner:
    """Signs hook calls exactly as EpicStaff does, for tests and local runs.

    EpicStaff signs gateway contexts and hook assertions with one key, so this signer uses the
    key of the `ContextSigner` it is given: a plugin process whose runtime file holds that
    signer's `jwks` accepts both.
    """

    def __init__(self, signer: ContextSigner):
        self._signer = signer

    def call(
        self,
        kind: HookKind,
        *,
        org: ContextOrganization | Mapping[str, Any] | None = None,
        job_id: int = 1,
        attempt: int = 1,
        previous_version: str | None = None,
        timeout_seconds: int | None = None,
        issued_at: int | None = None,
    ) -> HookCall:
        """Build and sign the hook call EpicStaff would send for this job.

        `org` defaults to `DEFAULT_ORGANIZATION`, `timeout_seconds` to the platform maximum
        for the kind, and `issued_at` to now.
        """
        request = HookRequest.model_validate(
            {
                "format": HOOK_REQUEST_FORMAT,
                "job_id": job_id,
                "attempt": attempt,
                "kind": kind,
                "org": DEFAULT_ORGANIZATION if org is None else org,
                "plugin": {
                    "identifier": self._signer.plugin_identifier,
                    "version": self._signer.plugin_version,
                },
                "previous_version": previous_version,
            }
        )
        body = encode_hook_body(request)
        now = int(time.time()) if issued_at is None else issued_at
        timeout = MAX_HOOK_TIMEOUT_SECONDS[kind] if timeout_seconds is None else timeout_seconds
        claims = HookAssertionClaims(
            iss=self._signer.issuer,
            aud=self._signer.plugin_identifier,
            iat=now,
            exp=now + timeout + HOOK_ASSERTION_GRACE_SECONDS,
            jti=secrets.token_hex(16),
            kind=kind,
            job_id=job_id,
            attempt=attempt,
            org_id=request.org.id,
            body_sha256=hook_body_sha256(body),
        )
        return HookCall(
            path=HOOK_PATHS[kind],
            headers={HOOK_HEADER: self.sign(claims), "Content-Type": "application/json"},
            body=body,
            request=request,
            claims=claims,
        )

    def sign(
        self,
        claims: HookAssertionClaims | Mapping[str, Any],
        *,
        headers: Mapping[str, Any] | None = None,
    ) -> str:
        """Sign claims as a hook assertion; arbitrary ones too, for tests of calls that must fail.

        `headers` replaces or adds header fields (`typ`, `kid`, ...).
        """
        payload = (
            claims.model_dump(mode="json") if isinstance(claims, HookAssertionClaims) else claims
        )
        return self._signer.sign_claims(
            payload, headers={"typ": HOOK_ASSERTION_TYPE, **(headers or {})}
        )
