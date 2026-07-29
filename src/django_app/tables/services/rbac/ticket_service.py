import secrets

from django.conf import settings
from django.contrib.auth import get_user_model
from django_redis import get_redis_connection


class TicketService:
    """
    Single-use, short-lived tickets stored in Redis for authenticating
    connections that cannot carry an Authorization header (WebSocket, SSE).

    The client POSTs with JWT to issue a ticket and then opens the connection
    URL with `?ticket=<value>`. Each ticket is consumed atomically via GETDEL
    (Redis 6.2+) so replay is impossible even under concurrent reconnects.
    """

    def __init__(self, prefix: str, ttl_seconds: int):
        self._prefix = prefix
        self._ttl_seconds = ttl_seconds

    def _redis(self):
        return get_redis_connection("default")

    def _key(self, ticket: str) -> str:
        return f"{self._prefix}{ticket}"

    def issue(self, user) -> tuple[str, int]:
        ticket = secrets.token_urlsafe(32)
        self._redis().set(self._key(ticket), user.pk, ex=self._ttl_seconds)
        return ticket, self._ttl_seconds

    def consume(self, ticket: str) -> object | None:
        if not ticket:
            return None
        raw = self._redis().getdel(self._key(ticket))
        if raw is None:
            return None
        try:
            user_id = int(raw)
        except (TypeError, ValueError):
            return None
        return get_user_model().objects.filter(pk=user_id).first()


ws_ticket_service = TicketService(
    prefix="rbac:ws_ticket:",
    ttl_seconds=settings.GRAPH_WS_TICKET_TTL_SECONDS,
)

sse_ticket_service = TicketService(
    prefix="rbac:sse_ticket:",
    ttl_seconds=settings.SSE_TICKET_TTL_SECONDS,
)
