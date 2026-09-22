"""
Registry of every audit domain this service knows about. Adding a new
audit type means adding one entry here (and its own
app/domains/<name>/domain.py) - nothing under app/filtering,
app/repositories, or app/services needs to change.
"""

from app.domains.base import AuditDomain
from app.domains.sessions.domain import SESSIONS

DOMAINS: dict[str, AuditDomain] = {SESSIONS.name: SESSIONS}


def get_domain(name: str) -> AuditDomain:
    """Plain KeyError, not a domain exception mapped to 404: nothing in this
    codebase looks up a domain by name from request input today (routes are
    mounted per-domain at startup via app.main.py's loop over
    DOMAINS.values(), not dispatched by a `{domain_name}` path parameter),
    so there's no HTTP boundary here to translate the error for yet. A
    lookup-by-name-from-a-request use case would want its own explicit
    try/except at that call site translating this into a 404 - not a
    blanket exception type baked into the registry itself."""
    try:
        return DOMAINS[name]
    except KeyError:
        raise KeyError(f"Unknown audit domain: {name!r}") from None
