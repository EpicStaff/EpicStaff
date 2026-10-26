"""Single-use authorization codes the browser exchanges for a plugin login token."""

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass

from django_redis import get_redis_connection

from plugins.identity.login_protocol import CODE_TTL_SECONDS

_KEY_PREFIX = "plugins:auth_code:"


@dataclass(frozen=True)
class AuthorizationCodeRecord:
    """What a code was issued for: one person, organization, grant and plugin, the PKCE
    challenge, and the plugin frame origin the exchange must come from.

    `password_fingerprint` is the `pwd` value of the person's password when the code was
    issued (`plugin_login_tokens.password_fingerprint`), so a password change in the code's
    60 s ends it like every session; it is an HMAC, never the password hash.
    """

    user_id: int
    org_id: int
    grant_id: int
    plugin: str
    code_challenge: str
    origin: str
    password_fingerprint: str
    issued_at: int


class PluginAuthorizationCodeService:
    """Issues and consumes codes, kept in Redis for `CODE_TTL_SECONDS` (60 s).

    As with `rbac.identity.tickets.TicketService`, Redis holds only the SHA-256 of a code, so
    read access to Redis yields nothing to exchange, and a code is consumed with `GETDEL`, so
    two exchanges racing for one code cannot both get it.
    """

    def issue(self, record: AuthorizationCodeRecord) -> str:
        """Store `record` under a new code and return the code (43 base64url characters)."""
        code = secrets.token_urlsafe(32)
        _redis().set(_key(code), json.dumps(asdict(record)), ex=CODE_TTL_SECONDS)
        return code

    def consume(self, code: str) -> AuthorizationCodeRecord | None:
        """Return the code's record and forget it, or None for an unknown, expired or used code."""
        raw = _redis().getdel(_key(code))
        if raw is None:
            return None
        return AuthorizationCodeRecord(**json.loads(raw))


def _redis():
    return get_redis_connection("default")


def _key(code: str) -> str:
    return f"{_KEY_PREFIX}{hashlib.sha256(code.encode('utf-8')).hexdigest()}"
