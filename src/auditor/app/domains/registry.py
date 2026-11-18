"""Every audit domain this service can serve, and the ones the deployment switched on."""

from app.core import settings
from app.domains.base import AuditDomain
from app.domains.sessions.domain import SESSIONS
from app.domains.user_actions.domain import USER_ACTIONS

ALL_DOMAINS: dict[str, AuditDomain] = {
    SESSIONS.name: SESSIONS,
    USER_ACTIONS.name: USER_ACTIONS,
}


def enabled_domains(
    *, sessions_enabled: bool, user_actions_enabled: bool
) -> dict[str, AuditDomain]:
    """Return the domains whose switch is on, keyed by name."""
    switches = {SESSIONS.name: sessions_enabled, USER_ACTIONS.name: user_actions_enabled}
    return {name: domain for name, domain in ALL_DOMAINS.items() if switches[name]}


DOMAINS: dict[str, AuditDomain] = enabled_domains(
    sessions_enabled=settings.SESSION_AUDIT_TRAIL_ENABLED,
    user_actions_enabled=settings.USER_AUDIT_TRAIL_ENABLED,
)


def get_domain(name: str) -> AuditDomain:
    """Returns the enabled domain called `name`; raises KeyError if unknown or switched off."""
    try:
        return DOMAINS[name]
    except KeyError:
        raise KeyError(f"Unknown audit domain: {name!r}") from None
