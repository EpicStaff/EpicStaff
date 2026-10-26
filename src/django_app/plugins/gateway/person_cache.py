"""The gateway's short-lived view of the person a plugin login token names.

Every request to a plugin's `/api/` checks the person behind its token. The facts come from
`plugin_access` and are kept in Django's cache (shared by every worker) for
`PERSON_CACHE_SECONDS`, keyed by plugin, organization, user, grant and the token's password
fingerprint: a token issued just after a password change never meets an entry built for the
old password. The token itself
(signature, expiry, claims) is checked on every request and never cached, so a deactivation,
password change, role change, membership removal or grant suspension takes effect within 10 s.
The cache holds the password's HMAC from the token's key, never the password hash.

The key also carries a tag of `GatewayPerson`'s shape (its fields and their types), so an
entry another release wrote in another shape is never read: during a deploy, old and new
processes share the cache and each reads only its own entries.
"""

import hashlib
import hmac
from dataclasses import asdict, dataclass, fields

from django.core.cache import cache

from plugins.access.plugin_access import gateway_person_facts
from plugins.identity.plugin_login_tokens import PluginLoginClaims, password_fingerprint

PERSON_CACHE_SECONDS = 10


@dataclass(frozen=True)
class GatewayPerson:
    """What the gateway knows about a token's person, organization and grant.

    `member` is whether the person is still an active member of the token's organization, and
    that organization active. `grant_usable` is false once the token's grant is suspended,
    deleted or re-created, or the plugin stops running; `grant_state` is that grant's state
    (None once it is gone), so an organization being upgraded gets its own answer. `may_use` is
    the `plugin_access` rule: an active member of an active organization whose role has `read`
    on the plugin, with the grant usable.
    """

    user_active: bool
    password_fingerprint: str
    member: bool
    grant_usable: bool
    grant_state: str | None
    may_use: bool
    organization_name: str
    email: str
    name: str
    actions: list[str]

    def holds(self, claims: PluginLoginClaims) -> bool:
        """Whether the token's person still holds: their user is active and their password is
        the one the token was issued with."""
        return self.user_active and hmac.compare_digest(
            self.password_fingerprint, claims.password_fingerprint
        )


def _shape_tag() -> str:
    shape = ",".join(f"{field.name}:{field.type}" for field in fields(GatewayPerson))
    return hashlib.sha256(shape.encode("utf-8")).hexdigest()[:12]


PERSON_SHAPE_TAG = _shape_tag()


def person_for(claims: PluginLoginClaims) -> GatewayPerson:
    """Return the gateway's view of the token's person, from the cache or built afresh."""
    key = cache_key(claims)
    cached = cache.get(key)
    if cached is not None:
        return GatewayPerson(**cached)
    person = _build(claims)
    cache.set(key, asdict(person), timeout=PERSON_CACHE_SECONDS)
    return person


def cache_key(claims: PluginLoginClaims) -> str:
    return (
        f"plugins:gw:person:{PERSON_SHAPE_TAG}:{claims.plugin}:{claims.org_id}:{claims.user_id}"
        f":{claims.grant_id}:{claims.password_fingerprint}"
    )


def _build(claims: PluginLoginClaims) -> GatewayPerson:
    facts = gateway_person_facts(
        user_id=claims.user_id,
        org_id=claims.org_id,
        grant_id=claims.grant_id,
        identifier=claims.plugin,
    )
    user = facts.user
    return GatewayPerson(
        user_active=user is not None and user.is_active,
        password_fingerprint=password_fingerprint(user.password) if user is not None else "",
        member=facts.membership is not None,
        grant_usable=facts.grant is not None,
        grant_state=facts.grant_state,
        may_use=facts.may_use,
        organization_name=facts.membership.org.name if facts.membership is not None else "",
        email=user.email if user is not None else "",
        name=user.effective_display_name if user is not None else "",
        actions=facts.actions,
    )
