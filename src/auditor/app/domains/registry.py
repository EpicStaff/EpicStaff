"""Every audit domain this service serves, keyed by name."""

from app.domains.base import AuditDomain
from app.domains.sessions.domain import SESSIONS

DOMAINS: dict[str, AuditDomain] = {SESSIONS.name: SESSIONS}


def get_domain(name: str) -> AuditDomain:
    """Returns the registered domain called `name`; raises KeyError if unknown."""
    try:
        return DOMAINS[name]
    except KeyError:
        raise KeyError(f"Unknown audit domain: {name!r}") from None
