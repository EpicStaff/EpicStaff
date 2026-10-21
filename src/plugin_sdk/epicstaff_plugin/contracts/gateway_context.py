"""Gateway context version 1: who and what a request reaching a plugin's backend is for.

EpicStaff's gateway check signs one context per request it forwards (a compact JWS, EdDSA over
Ed25519) and nginx passes it to the plugin process in `X-EpicStaff-Plugin-Context`. The plugin
verifies it with the public keys of EpicStaff's JWKS; it can read the context but never forge
one. `epicstaff_plugin.gateway.ContextVerifier` holds the verification steps.

Every model forbids unknown fields, so the side that builds a document cannot misspell one.
The side that reads one parses it leniently, so a newer EpicStaff that adds a claim does not
break a plugin built against an older SDK:

    GatewayContext.model_validate(claims, extra="ignore")

Pydantic applies the per-call `extra` to every nested model.
"""

import base64
import binascii
from typing import Annotated, Literal, Self

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from epicstaff_plugin.contracts.manifest import IDENTIFIER_PATTERN, Action, Version

CONTEXT_HEADER = "X-EpicStaff-Plugin-Context"
CONTEXT_TYPE = "epicstaff-plugin-context+jwt"
CONTEXT_ALGORITHM = "EdDSA"
CONTEXT_LIFETIME_SECONDS = 60
# How far a plugin's clock may run ahead of EpicStaff's before a fresh context looks expired.
CONTEXT_LEEWAY_SECONDS = 30

KEY_ID_PATTERN = r"^[0-9a-f]{16}$"
# Base64url without padding of a raw 32-byte Ed25519 public key.
ED25519_X_PATTERN = r"^[A-Za-z0-9_-]{43}$"
JTI_PATTERN = r"^[0-9a-f]{32}$"
REQUEST_METHOD_PATTERN = r"^[A-Z]{1,20}$"
MAX_REQUEST_PATH_LENGTH = 8192

PluginIdentifier = Annotated[str, StringConstraints(pattern=IDENTIFIER_PATTERN)]
KeyId = Annotated[str, StringConstraints(pattern=KEY_ID_PATTERN)]
ContextMode = Literal["public", "user"]


class _ContextContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Jwk(_ContextContractModel):
    """One Ed25519 public key EpicStaff signs contexts with (RFC 8037 `OKP` form)."""

    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: Annotated[str, StringConstraints(pattern=ED25519_X_PATTERN)]
    kid: KeyId
    alg: Literal["EdDSA"]
    use: Literal["sig"]

    @classmethod
    def from_public_key(cls, kid: str, public_key: Ed25519PublicKey) -> Self:
        """Describe `public_key` as the JWK published under `kid`."""
        raw = public_key.public_bytes(Encoding.Raw, PublicFormat.Raw)
        x = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
        return cls(kty="OKP", crv="Ed25519", x=x, kid=kid, alg="EdDSA", use="sig")

    def public_key(self) -> Ed25519PublicKey:
        try:
            raw = base64.urlsafe_b64decode(self.x + "=")
        except (binascii.Error, ValueError):
            raise ValueError(f"key {self.kid} is not valid base64url") from None
        return Ed25519PublicKey.from_public_bytes(raw)


class Jwks(_ContextContractModel):
    """EpicStaff's context-signing keys: the active one and those retired less than 24 h ago.

    Published at `GET /api/plugin-public/jwks/` and copied into every runtime file.
    """

    keys: Annotated[list[Jwk], Field(min_length=1)]

    @field_validator("keys")
    @classmethod
    def _distinct_key_ids(cls, keys: list[Jwk]) -> list[Jwk]:
        key_ids = [key.kid for key in keys]
        if len(set(key_ids)) != len(key_ids):
            raise ValueError("lists a key id more than once")
        return keys

    def find(self, kid: str) -> Jwk | None:
        return next((key for key in self.keys if key.kid == kid), None)


class PluginIdentity(_ContextContractModel):
    """The plugin and the version of it that is running."""

    identifier: PluginIdentifier
    version: Version


class ContextOrganization(_ContextContractModel):
    """The EpicStaff organization the request is made in."""

    id: Annotated[int, Field(gt=0)]
    name: Annotated[str, StringConstraints(max_length=255)]


class ContextUser(_ContextContractModel):
    """The EpicStaff user the request is made by."""

    id: Annotated[int, Field(gt=0)]
    email: Annotated[str, StringConstraints(max_length=254)]
    name: Annotated[str, StringConstraints(max_length=300)]


class ContextRequest(_ContextContractModel):
    """The request the context was issued for; the plugin checks it matches the one it got.

    `path` is the canonical, percent-decoded path without the query string, as the plugin's
    ASGI server sees it in `scope["path"]`.
    """

    method: Annotated[str, StringConstraints(pattern=REQUEST_METHOD_PATTERN)]
    path: Annotated[str, StringConstraints(min_length=1, max_length=MAX_REQUEST_PATH_LENGTH)]

    @field_validator("path")
    @classmethod
    def _canonical_path(cls, path: str) -> str:
        if not path.startswith("/"):
            raise ValueError("must start with '/'")
        if any(segment in (".", "..") for segment in path.split("/")):
            raise ValueError("must not contain '.' or '..' segments")
        return path


class GatewayContext(_ContextContractModel):
    """The claims of a gateway context, the payload of `X-EpicStaff-Plugin-Context`.

    `mode` is `public` on a path the manifest declares public: there is no user and no
    organization, and `permissions` is empty. `user` contexts carry the person's plugin
    permissions in the organization the request is made in.
    """

    iss: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    """EpicStaff's public origin; equals the runtime file's `issuer`."""

    aud: PluginIdentifier
    """The plugin the context is for; equals `plugin.identifier`."""

    iat: Annotated[int, Field(ge=0)]
    exp: Annotated[int, Field(ge=0)]
    jti: Annotated[str, StringConstraints(pattern=JTI_PATTERN)]
    plugin: PluginIdentity
    org: ContextOrganization | None
    user: ContextUser | None
    permissions: list[Action]
    """The plugin actions (`read`, `update`, ...) the user holds; empty for a public request."""

    request: ContextRequest
    mode: ContextMode

    @model_validator(mode="after")
    def _consistent_claims(self) -> Self:
        if self.aud != self.plugin.identifier:
            raise ValueError("aud must equal plugin.identifier")
        if self.exp <= self.iat:
            raise ValueError("exp must be later than iat")
        if len(set(self.permissions)) != len(self.permissions):
            raise ValueError("permissions lists an action more than once")
        if self.mode == "public" and (
            self.user is not None or self.org is not None or self.permissions
        ):
            raise ValueError("a public context has no user, no organization and no permissions")
        return self


def encode_context(context: GatewayContext, private_key: Ed25519PrivateKey, kid: str) -> str:
    """Sign `context` as the compact JWS EpicStaff sends in `X-EpicStaff-Plugin-Context`.

    The header is `{"alg": "EdDSA", "typ": "epicstaff-plugin-context+jwt", "kid": kid}`.
    """
    return jwt.encode(
        context.model_dump(mode="json"),
        private_key,
        algorithm=CONTEXT_ALGORITHM,
        headers={"typ": CONTEXT_TYPE, "kid": kid},
    )
