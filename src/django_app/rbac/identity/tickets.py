import hashlib
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.contrib.auth import get_user_model
from django_redis import get_redis_connection


def ticket_digest(ticket: str) -> str:
    """Derive the storage form of a ticket. Pure - no I/O."""
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class TicketHolder:
    """Who a consumed ticket authenticates.

    Attributes:
        api_key_org_id: The org of the USER API key the ticket was issued with, or None
            for a session ticket. A key acts only in its own org, so a stream opened
            with its ticket must refuse every row of another org.
    """

    user: object
    api_key_org_id: int | None


class TicketService:
    """
    Single-use, short-lived tickets stored in Redis for authenticating
    connections that cannot carry an Authorization header (WebSocket, SSE).

    The client POSTs with JWT or a USER API key to issue a ticket and then
    opens the connection URL with `?ticket=<value>`. Each ticket is consumed
    atomically via GETDEL (Redis 6.2+) so replay is impossible even under
    concurrent reconnects.

    Redis holds only the SHA-256 digest of a ticket, never the ticket itself,
    so read access to Redis yields no replayable credential.
    """

    def __init__(self, prefix: str, ttl_seconds: int) -> None:
        self._prefix = prefix
        self._ttl_seconds = ttl_seconds

    def _redis(self):
        return get_redis_connection("default")

    def _key(self, ticket: str) -> str:
        return f"{self._prefix}{ticket_digest(ticket)}"

    def issue(self, user, api_key_org_id: int | None = None) -> tuple[str, int]:
        """Issue a ticket for `user`; pass `api_key_org_id` when the request used a USER key."""
        ticket = secrets.token_urlsafe(32)
        # "<user id>" for a session, "<user id>:<key org id>" for a USER API key.
        value = user.pk if api_key_org_id is None else f"{user.pk}:{api_key_org_id}"
        self._redis().set(self._key(ticket), value, ex=self._ttl_seconds)
        return ticket, self._ttl_seconds

    def consume(self, ticket: str) -> TicketHolder | None:
        """Redeem `ticket` once; None when it is unknown, expired, malformed or its user is gone."""
        if not isinstance(ticket, str) or not ticket:
            return None
        raw = self._redis().getdel(self._key(ticket))
        if raw is None:
            return None
        try:
            value = raw.decode() if isinstance(raw, bytes) else str(raw)
            user_part, separator, org_part = value.partition(":")
            user_id = int(user_part)
            api_key_org_id = int(org_part) if separator else None
        except ValueError:
            return None
        user = get_user_model().objects.filter(pk=user_id).first()
        if user is None:
            return None
        return TicketHolder(user=user, api_key_org_id=api_key_org_id)


ws_ticket_service = TicketService(
    prefix="rbac:ws_ticket:",
    ttl_seconds=settings.GRAPH_WS_TICKET_TTL,
)

sse_ticket_service = TicketService(
    prefix="rbac:sse_ticket:",
    ttl_seconds=settings.SSE_TICKET_TTL,
)
