"""Hook API version 1: how EpicStaff calls a plugin backend's lifecycle hooks.

EpicStaff decides that a hook runs (an organization was granted the plugin, for example) and
the node calls the plugin process over loopback:

    POST http://127.0.0.1:<port><HOOK_PATHS[kind]>
    X-EpicStaff-Hook: <assertion>
    Content-Type: application/json

    <the HookRequest, as exact JSON bytes>

The assertion is a compact JWS (EdDSA over Ed25519) that EpicStaff signs with the key it signs
gateway contexts with; its `typ` keeps the two apart. It names the plugin, the hook and the
organization, and binds the exact body bytes through their SHA-256, so another process on the
node can neither forge a hook call nor replay an assertion with another body. The plugin
verifies it with `epicstaff_plugin.hooks.verify_hook_assertion`, which
`python -m epicstaff_plugin.serve` runs on every hook call.

The plugin answers `200 {"status": "done"}` when the hook succeeded. Any other answer fails the
hook: `{"status": "failed", "error": {"message": "..."}}` with a status that says why.

Every model forbids unknown fields, so the side that builds a document cannot misspell one.
The side that reads one parses it leniently, so a newer EpicStaff that adds a field does not
break a plugin built against an older SDK:

    HookRequest.model_validate_json(body, extra="ignore")

EpicStaff retries some failed hooks on its own. An organization removed hook is retried on the
schedule `org_removed_retry_delay` gives, until `ORG_REMOVED_RETRY_WINDOW_SECONDS` after its
first attempt. An upgrade hook is retried after each of its first failures in a row, as
`upgrade_retry_delay` gives, and then waits for a SuperAdmin to retry it. An install hook waits
for a SuperAdmin after its first failure.

Adding a hook kind: `HookKind` and `HOOK_PATHS` here, then EpicStaff's job kind and the
lifecycle step that creates the job, then the registration method of
`epicstaff_plugin.hooks.HookRegistry`. A kind whose organization holds no key when it runs goes
in `KEYLESS_HOOK_KINDS` too. A kind that EpicStaff retries on its own also gets its retry
constants here, then their use where EpicStaff records a hook's result, then its row in the
hook API reference.
"""

import hashlib
from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal, Self, get_args

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    StringConstraints,
    model_validator,
)

from epicstaff_plugin.contracts.gateway_context import (
    JTI_PATTERN,
    ContextOrganization,
    PluginIdentifier,
    PluginIdentity,
)
from epicstaff_plugin.contracts.manifest import Version

HookKind = Literal["install", "upgrade", "org_removed"]
HOOK_KINDS: tuple[str, ...] = get_args(HookKind)
HOOK_PATHS: Mapping[str, str] = MappingProxyType(
    {
        "install": "/_epicstaff/hooks/install",
        "upgrade": "/_epicstaff/hooks/upgrade",
        "org_removed": "/_epicstaff/hooks/org-removed",
    }
)
KEYLESS_HOOK_KINDS: frozenset[str] = frozenset({"org_removed"})
"""The kinds whose organization no longer holds a service-account key when the hook runs.

The plugin's handler gets no EpicStaff client for them, and the node runs them without waiting
for the organization's key in the runtime file. Every other kind's handler gets an `OrgClient`.
"""
HOOK_HEADER = "X-EpicStaff-Hook"
HOOK_ASSERTION_TYPE = "epicstaff-plugin-hook+jwt"
HOOK_ASSERTION_ALGORITHM = "EdDSA"
# How far a plugin's clock may run ahead of EpicStaff's before a fresh assertion looks expired.
HOOK_ASSERTION_LEEWAY_SECONDS = 30
# An assertion expires this long after the hook's timeout, counted from when it was signed.
HOOK_ASSERTION_GRACE_SECONDS = 60
MAX_HOOK_ASSERTION_LENGTH = 8192
HOOK_REQUEST_FORMAT = 1
MAX_HOOK_BODY_BYTES = 16384
MAX_HOOK_ERROR_MESSAGE_LENGTH = 2000

BODY_SHA256_PATTERN = r"^[0-9a-f]{64}$"

ORG_REMOVED_RETRY_DELAYS_SECONDS = (60, 300, 1800, 3600)
"""Seconds EpicStaff waits before the next attempt of a failed organization removed hook: after
attempt 1, 2 and 3, then the last value after every later attempt."""
ORG_REMOVED_RETRY_WINDOW_SECONDS = 7 * 24 * 60 * 60
"""How long after its first attempt a failing organization removed hook is still retried; after
that it stays failed until a SuperAdmin retries or skips it."""


def org_removed_retry_delay(attempt: int) -> int:
    """Return the seconds before the next attempt, after attempt number `attempt` failed.

    Raises:
        ValueError: `attempt` is not a positive integer.
    """
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError(f"an attempt number is a positive integer, not {attempt!r}")
    return ORG_REMOVED_RETRY_DELAYS_SECONDS[min(attempt, len(ORG_REMOVED_RETRY_DELAYS_SECONDS)) - 1]


UPGRADE_RETRY_DELAYS_SECONDS = (60, 300)
"""Seconds EpicStaff waits before it tries a failed upgrade hook again: after the first and the
second failure in a row. After the third it stops; the organization's upgrade stays failed until
a SuperAdmin retries it, which starts a new series."""


def upgrade_retry_delay(failures_in_series: int) -> int | None:
    """Return the seconds before the next attempt, after this many failures in a row.

    None means EpicStaff tries no more on its own: the organization's upgrade has failed, and
    waits for a SuperAdmin's Retry.

    Raises:
        ValueError: `failures_in_series` is not a positive integer.
    """
    if (
        isinstance(failures_in_series, bool)
        or not isinstance(failures_in_series, int)
        or failures_in_series < 1
    ):
        raise ValueError(
            f"a number of failures in a row is a positive integer, not {failures_in_series!r}"
        )
    if failures_in_series > len(UPGRADE_RETRY_DELAYS_SECONDS):
        return None
    return UPGRADE_RETRY_DELAYS_SECONDS[failures_in_series - 1]


class _HookContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HookAssertionClaims(_HookContractModel):
    """The claims of a hook assertion, the payload of `X-EpicStaff-Hook`.

    `exp` is `iat` plus the hook's timeout plus 60 seconds. `job_id`, `attempt`, `kind` and
    `org_id` repeat the body's, and `body_sha256` is the hex SHA-256 of the exact body bytes.
    """

    iss: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    """EpicStaff's public origin; equals the runtime file's `issuer`."""

    aud: PluginIdentifier
    """The plugin the hook is for."""

    iat: Annotated[int, Field(ge=0)]
    exp: Annotated[int, Field(ge=0)]
    jti: Annotated[str, StringConstraints(pattern=JTI_PATTERN)]
    kind: HookKind
    job_id: PositiveInt
    attempt: PositiveInt
    org_id: PositiveInt
    body_sha256: Annotated[str, StringConstraints(pattern=BODY_SHA256_PATTERN)]

    @model_validator(mode="after")
    def _expires_after_issue(self) -> Self:
        if self.exp <= self.iat:
            raise ValueError("exp must be later than iat")
        return self


class HookRequest(_HookContractModel):
    """The body of a hook call: which job, which attempt, for which organization.

    A retried job keeps its `job_id` and gets the next `attempt`; a handler that already did
    the work for a `job_id` must succeed again without doing it twice.

    `previous_version` is set for an upgrade: the version the organization was last brought
    to, which may be several versions back (compare it with `epicstaff_plugin.versions`). It is
    null for an upgrade only when the organization never finished installing an earlier
    version, so the hook sets everything up as an install would. It is null for every other
    kind.
    """

    format: Literal[1]
    job_id: PositiveInt
    attempt: PositiveInt
    kind: HookKind
    org: ContextOrganization
    plugin: PluginIdentity
    previous_version: Version | None


class HookError(_HookContractModel):
    """Why a hook failed, in words a SuperAdmin can act on."""

    message: Annotated[str, StringConstraints(max_length=MAX_HOOK_ERROR_MESSAGE_LENGTH)]


class HookResponse(_HookContractModel):
    """The plugin's answer to a hook call: `done`, or `failed` with an error."""

    status: Literal["done", "failed"]
    error: HookError | None = None

    @model_validator(mode="after")
    def _error_only_when_failed(self) -> Self:
        if self.status == "done" and self.error is not None:
            raise ValueError("a done hook has no error")
        if self.status == "failed" and self.error is None:
            raise ValueError("a failed hook has an error")
        return self

    @property
    def succeeded(self) -> bool:
        return self.status == "done"


def hook_body_sha256(body: bytes) -> str:
    """Return the `body_sha256` claim for a hook body: the hex SHA-256 of its exact bytes."""
    return hashlib.sha256(body).hexdigest()


def encode_hook_body(request: HookRequest) -> bytes:
    """Return the exact bytes EpicStaff sends, and digests, as a hook's body."""
    return request.model_dump_json().encode("utf-8")


def encode_hook_assertion(
    claims: HookAssertionClaims, private_key: Ed25519PrivateKey, kid: str
) -> str:
    """Sign `claims` as the compact JWS EpicStaff sends in `X-EpicStaff-Hook`.

    The header is `{"alg": "EdDSA", "typ": "epicstaff-plugin-hook+jwt", "kid": kid}`.
    """
    return jwt.encode(
        claims.model_dump(mode="json"),
        private_key,
        algorithm=HOOK_ASSERTION_ALGORITHM,
        headers={"typ": HOOK_ASSERTION_TYPE, "kid": kid},
    )
