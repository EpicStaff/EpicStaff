"""The proof that a plugin host is served by this EpicStaff, as both sides compute it.

Every plugin host answers `GET /.well-known/epicstaff/instance?challenge=<challenge>` through
nginx (`plugins-server-true.snippet`) with `HMAC-SHA256(key, "<plugin host>\\n<challenge>")`.
Only this deployment holds the key, so a host that answers with it reaches this deployment's
nginx, and an answer for one host is no answer for another. The key is derived from
`PLUGINS_GATEWAY_SECRET` under a fixed label, so it is never the secret itself and needs no
setting of its own; rotating the secret changes it.
"""

import hashlib
import hmac

from django.conf import settings

INSTANCE_PATH = "/.well-known/epicstaff/instance"
CHALLENGE_PARAMETER = "challenge"
# `secrets.token_urlsafe(32)`: 43 base64url characters.
CHALLENGE_PATTERN = r"[A-Za-z0-9_-]{43}"
_KEY_LABEL = b"epicstaff plugin host proof v1"


def host_proof(host: str, challenge: str) -> str:
    """The hex HMAC that proves `host` reaches this deployment, for `challenge`."""
    secret = (settings.PLUGINS_GATEWAY_SECRET or "").encode("utf-8")
    key = hmac.new(secret, _KEY_LABEL, hashlib.sha256).digest()
    return hmac.new(key, f"{host}\n{challenge}".encode(), hashlib.sha256).hexdigest()
