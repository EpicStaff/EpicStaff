"""Signed, expiring tokens that let a sandboxed plugin page load its own files.

The page runs in an opaque-origin iframe with no credentials, so the token in its
URL is the only thing that authorizes its asset requests. It names the plugin,
the org and the user it was issued for; the asset view re-checks all three on
every request. It is reusable until it expires so the page's relative
`<script src>` and `<link href>` resolve under the same token.
"""

from dataclasses import dataclass

from django.core import signing

SALT = "plugins.ui"
# The page loads lazy chunks long after it opened, all under the token it was given,
# so the token lives as long as a page is reasonably kept open.
MAX_AGE_SECONDS = 12 * 60 * 60


@dataclass(frozen=True)
class UiTokenClaims:
    plugin_pk: int
    org_id: int
    user_id: int


def issue(claims: UiTokenClaims) -> str:
    return signing.dumps(
        {"plugin": claims.plugin_pk, "org": claims.org_id, "user": claims.user_id}, salt=SALT
    )


def read(token: str) -> UiTokenClaims | None:
    """The claims of a genuine, unexpired token; None for anything else."""
    try:
        payload = signing.loads(token, salt=SALT, max_age=MAX_AGE_SECONDS)
    except signing.BadSignature:
        # SignatureExpired is a BadSignature too.
        return None
    if not isinstance(payload, dict):
        return None
    values = (payload.get("plugin"), payload.get("org"), payload.get("user"))
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in values):
        return None
    return UiTokenClaims(*values)
