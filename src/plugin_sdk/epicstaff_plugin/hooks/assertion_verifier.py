"""Verification of the assertion EpicStaff signs for every hook call (`X-EpicStaff-Hook`)."""

import hmac
from dataclasses import dataclass

import jwt
from pydantic import ValidationError

from epicstaff_plugin.contracts.gateway_context import Jwk, Jwks
from epicstaff_plugin.contracts.hook_api import (
    HOOK_ASSERTION_ALGORITHM,
    HOOK_ASSERTION_LEEWAY_SECONDS,
    HOOK_ASSERTION_TYPE,
    MAX_HOOK_ASSERTION_LENGTH,
    MAX_HOOK_BODY_BYTES,
    HookAssertionClaims,
    HookKind,
    HookRequest,
    hook_body_sha256,
)
from epicstaff_plugin.runtime.signing_keys import SigningKeys

_REQUIRED_CLAIMS = ["iss", "aud", "iat", "exp", "jti"]


class HookAssertionRejected(Exception):  # noqa: N818 (named like ContextRejected)
    """A hook call's assertion is missing, or it or the body fails a check.

    `reason` names the check: `missing`, `ambiguous`, `malformed`, `wrong_type`,
    `unknown_key`, `bad_signature`, `expired`, `not_yet_valid`, `wrong_audience`,
    `wrong_issuer`, `invalid_claims`, `wrong_kind`, `body_too_large`,
    `body_digest_mismatch`, `invalid_body` or `body_mismatch`.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class VerifiedHook:
    """A hook call that passed every check: its assertion's claims and its body."""

    claims: HookAssertionClaims
    request: HookRequest


def verify_hook_assertion(
    assertion: str,
    body: bytes,
    *,
    kind: HookKind,
    jwks: Jwks,
    issuer: str,
    plugin_identifier: str,
) -> VerifiedHook:
    """Verify a hook call: the assertion EpicStaff signed, and the body it was sent with.

    The call passes when the signature verifies with the key the assertion's `kid` names in
    `jwks`, its `typ` is `epicstaff-plugin-hook+jwt`, `aud` is `plugin_identifier`, `iss` is
    `issuer`, it has not expired (30 s leeway), its `kind` is the `kind` of the path it was
    posted to, `body_sha256` is the SHA-256 of `body`, and the body's job, attempt, kind,
    organization and plugin are the assertion's.

    Raises:
        HookAssertionRejected: The call fails a check.
    """
    kid = _preflight(assertion)
    key = jwks.find(kid)
    if key is None:
        raise HookAssertionRejected("unknown_key")
    return _verified(assertion, body, kind, key, issuer, plugin_identifier)


class HookAssertionVerifier:
    """Checks hook calls for one plugin process, with the keys its runtime file names.

    A key the runtime file does not list yet is downloaded under the same rule as for gateway
    contexts (`SigningKeys`); the issuer and the plugin come from the same version of the
    runtime file as the key.
    """

    def __init__(self, signing_keys: SigningKeys):
        self._keys = signing_keys

    async def verify_async(self, assertion: str, body: bytes, kind: HookKind) -> VerifiedHook:
        """Verify a hook call posted to the path of `kind`, as `verify_hook_assertion` does.

        Raises:
            HookAssertionRejected: The call fails a check.
        """
        kid = _preflight(assertion)
        resolved = await self._keys.find_or_download_async(kid)
        if resolved is None:
            raise HookAssertionRejected("unknown_key")
        document = resolved.document
        return _verified(
            assertion, body, kind, resolved.jwk, document.issuer, document.plugin.identifier
        )


def _preflight(assertion: str) -> str:
    if not assertion or len(assertion) > MAX_HOOK_ASSERTION_LENGTH:
        raise HookAssertionRejected("malformed")
    try:
        header = jwt.get_unverified_header(assertion)
    except jwt.InvalidTokenError:
        raise HookAssertionRejected("malformed") from None
    if header.get("typ") != HOOK_ASSERTION_TYPE:
        raise HookAssertionRejected("wrong_type")
    if header.get("alg") != HOOK_ASSERTION_ALGORITHM:
        raise HookAssertionRejected("malformed")
    kid = header.get("kid")
    if not isinstance(kid, str):
        raise HookAssertionRejected("malformed")
    return kid


def _verified(
    assertion: str, body: bytes, kind: str, key: Jwk, issuer: str, plugin_identifier: str
) -> VerifiedHook:
    claims = _verified_claims(assertion, key, issuer, plugin_identifier)
    if claims.kind != kind:
        raise HookAssertionRejected("wrong_kind")
    if len(body) > MAX_HOOK_BODY_BYTES:
        raise HookAssertionRejected("body_too_large")
    if not hmac.compare_digest(hook_body_sha256(body), claims.body_sha256):
        raise HookAssertionRejected("body_digest_mismatch")
    try:
        request = HookRequest.model_validate_json(body, extra="ignore")
    except ValidationError:
        raise HookAssertionRejected("invalid_body") from None
    if (
        request.job_id != claims.job_id
        or request.attempt != claims.attempt
        or request.kind != claims.kind
        or request.org.id != claims.org_id
        or request.plugin.identifier != claims.aud
    ):
        raise HookAssertionRejected("body_mismatch")
    return VerifiedHook(claims=claims, request=request)


def _verified_claims(
    assertion: str, key: Jwk, issuer: str, plugin_identifier: str
) -> HookAssertionClaims:
    try:
        public_key = key.public_key()
    except ValueError:
        raise HookAssertionRejected("unknown_key") from None
    try:
        claims = jwt.decode(
            assertion,
            public_key,
            algorithms=[HOOK_ASSERTION_ALGORITHM],
            audience=plugin_identifier,
            issuer=issuer,
            leeway=HOOK_ASSERTION_LEEWAY_SECONDS,
            options={"require": _REQUIRED_CLAIMS},
        )
    except jwt.InvalidSignatureError:
        raise HookAssertionRejected("bad_signature") from None
    except jwt.ExpiredSignatureError:
        raise HookAssertionRejected("expired") from None
    except jwt.ImmatureSignatureError:
        raise HookAssertionRejected("not_yet_valid") from None
    except jwt.InvalidAudienceError:
        raise HookAssertionRejected("wrong_audience") from None
    except jwt.InvalidIssuerError:
        raise HookAssertionRejected("wrong_issuer") from None
    except jwt.DecodeError:
        raise HookAssertionRejected("malformed") from None
    except jwt.InvalidTokenError:
        raise HookAssertionRejected("invalid_claims") from None
    try:
        return HookAssertionClaims.model_validate(claims, extra="ignore")
    except ValidationError:
        raise HookAssertionRejected("invalid_claims") from None
