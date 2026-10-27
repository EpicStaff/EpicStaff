"""Plugin login tokens: what a plugin page sends to its own `/api/` as `Authorization: Bearer`.

A compact JWT (HS256) for one person, organization, grant and plugin, valid for 15 minutes. Its
key is derived from `SECRET_KEY` with HKDF under a label of its own, so simplejwt (which signs
EpicStaff's own tokens with `SECRET_KEY` itself) rejects its signature, and its `token_type`
is no simplejwt type: EpicStaff's API never accepts it. Only the gateway check verifies it.
Rotating `SECRET_KEY` ends every token.

The `pwd` claim binds the token to the person's password: it is an HMAC of the password hash
under the same key, so the page that holds the token learns nothing stable about the hash.
"""

import hashlib
import hmac
import re
import secrets
import time
from dataclasses import dataclass

import jwt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings

from plugins.identity.login_protocol import TOKEN_LIFETIME_SECONDS
from plugins.origins import PluginOrigins

TOKEN_TYPE_HEADER = "epicstaff-plugin-login+jwt"
TOKEN_TYPE_CLAIM = "plugin_login"
ALGORITHM = "HS256"
_KEY_LABEL = b"epicstaff.plugin-login.v1"
_PASSWORD_FINGERPRINT_LENGTH = 32
_REQUIRED_CLAIMS = ["exp", "iat", "sub", "aud", "iss", "jti"]
_POSITIVE_INTEGER = re.compile(r"[1-9][0-9]{0,18}")
_PASSWORD_FINGERPRINT = re.compile(r"[0-9a-f]{32}")


class PluginLoginTokenRejected(Exception):  # noqa: N818 (named like the SDK's ContextRejected)
    """A plugin login token fails a check; `reason` names which one. Never shown to a client."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class PluginLoginClaims:
    """The claims of a verified token that the gateway acts on."""

    user_id: int
    org_id: int
    grant_id: int
    plugin: str
    password_fingerprint: str
    jti: str


@dataclass(frozen=True)
class IssuedPluginLoginToken:
    token: str
    jti: str
    expires_in: int


def signing_key() -> bytes:
    """Return the 32-byte HMAC key of plugin login tokens, derived from `SECRET_KEY`."""
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=_KEY_LABEL).derive(
        settings.SECRET_KEY.encode("utf-8")
    )


def password_fingerprint(password_hash: str, key: bytes | None = None) -> str:
    """Return the `pwd` claim for a password hash: the first 32 hex digits of its HMAC-SHA256."""
    digest = hmac.new(key or signing_key(), password_hash.encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()[:_PASSWORD_FINGERPRINT_LENGTH]


def issue_plugin_login_token(
    *, user, org_id: int, grant_id: int, identifier: str
) -> IssuedPluginLoginToken:
    """Sign a token for `user` in organization `org_id` through grant `grant_id` of the plugin."""
    origins = PluginOrigins()
    key = signing_key()
    issued_at = int(time.time())
    jti = secrets.token_hex(16)
    claims = {
        "token_type": TOKEN_TYPE_CLAIM,
        "iss": origins.epicstaff_origin,
        "aud": origins.frame_origin(identifier),
        "sub": str(user.pk),
        "org": org_id,
        "plugin": identifier,
        "grant": grant_id,
        "pwd": password_fingerprint(user.password, key),
        "iat": issued_at,
        "exp": issued_at + TOKEN_LIFETIME_SECONDS,
        "jti": jti,
    }
    token = jwt.encode(claims, key, algorithm=ALGORITHM, headers={"typ": TOKEN_TYPE_HEADER})
    return IssuedPluginLoginToken(token=token, jti=jti, expires_in=TOKEN_LIFETIME_SECONDS)


def looks_like_plugin_login_token(token: str) -> bool:
    """Whether `token`'s unverified header names it a plugin login token.

    Only for keeping such a token away from a plugin process; it proves nothing about the token.
    """
    try:
        return jwt.get_unverified_header(token).get("typ") == TOKEN_TYPE_HEADER
    except jwt.InvalidTokenError:
        return False


def verify_plugin_login_token(token: str, identifier: str) -> PluginLoginClaims:
    """Verify `token` for the plugin `identifier` (its `aud` is that plugin's frame origin).

    Checks the header's `typ` and `alg` exactly, the signature, `iss`, `aud`, `exp` (no
    leeway), the required claims, `token_type` and `plugin`. Nothing here is cached.

    Raises:
        PluginLoginTokenRejected: Any check fails.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.InvalidTokenError:
        raise PluginLoginTokenRejected("malformed") from None
    if header.get("typ") != TOKEN_TYPE_HEADER:
        raise PluginLoginTokenRejected("wrong_type")
    if header.get("alg") != ALGORITHM:
        raise PluginLoginTokenRejected("wrong_algorithm")
    origins = PluginOrigins()
    try:
        claims = jwt.decode(
            token,
            signing_key(),
            algorithms=[ALGORITHM],
            audience=origins.frame_origin(identifier),
            issuer=origins.epicstaff_origin,
            options={"require": _REQUIRED_CLAIMS},
            leeway=0,
        )
    except jwt.ExpiredSignatureError:
        raise PluginLoginTokenRejected("expired") from None
    except jwt.InvalidAudienceError:
        raise PluginLoginTokenRejected("wrong_audience") from None
    except jwt.InvalidIssuerError:
        raise PluginLoginTokenRejected("wrong_issuer") from None
    except jwt.InvalidSignatureError:
        raise PluginLoginTokenRejected("bad_signature") from None
    except jwt.InvalidTokenError:
        raise PluginLoginTokenRejected("invalid_claims") from None
    if claims.get("token_type") != TOKEN_TYPE_CLAIM:
        raise PluginLoginTokenRejected("wrong_token_type")
    if claims.get("plugin") != identifier:
        raise PluginLoginTokenRejected("wrong_plugin")
    return _parsed_claims(claims)


def _parsed_claims(claims: dict) -> PluginLoginClaims:
    subject = claims["sub"]
    organization = claims.get("org")
    grant = claims.get("grant")
    fingerprint = claims.get("pwd")
    if not (
        isinstance(subject, str)
        and _POSITIVE_INTEGER.fullmatch(subject)
        and _is_positive_integer(organization)
        and _is_positive_integer(grant)
        and isinstance(fingerprint, str)
        and _PASSWORD_FINGERPRINT.fullmatch(fingerprint)
        and isinstance(claims["jti"], str)
    ):
        raise PluginLoginTokenRejected("invalid_claims")
    return PluginLoginClaims(
        user_id=int(subject),
        org_id=organization,
        grant_id=grant,
        plugin=claims["plugin"],
        password_fingerprint=fingerprint,
        jti=claims["jti"],
    )


def _is_positive_integer(value) -> bool:
    # bool is an int in Python; a token saying `"org": true` is not organization 1.
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
