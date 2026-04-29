import secrets
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django_redis import get_redis_connection


class SseTicketService:
    """
    Single-use, short-lived tickets that authenticate SSE (EventSource)
    connections. EventSource cannot attach an `Authorization` header, so the
    client POSTs with JWT to issue a ticket and then opens the SSE URL with
    `?ticket=<value>`. The ticket is consumed on first read, so reconnects
    require a fresh ticket.

    State lives in Redis and is read/written via the raw `django-redis`
    client so that consume can use `GETDEL` (Redis 6.2+) for atomic
    get-and-delete. Without that, a parallel pair of consumers could both
    pass the `GET` check before either `DEL` ran, breaking the single-use
    contract.
    """

    CACHE_PREFIX = "rbac:sse_ticket:"

    @property
    def ttl_seconds(self) -> int:
        return settings.SSE_TICKET_TTL_SECONDS

    def _redis(self):
        return get_redis_connection("default")

    def _cache_key(self, ticket: str) -> str:
        return f"{self.CACHE_PREFIX}{ticket}"

    def issue(self, user) -> Tuple[str, int]:
        ticket = secrets.token_urlsafe(32)
        self._redis().set(self._cache_key(ticket), user.pk, ex=self.ttl_seconds)
        return ticket, self.ttl_seconds

    def consume(self, ticket: str) -> Optional[object]:
        if not ticket:
            return None
        raw = self._redis().getdel(self._cache_key(ticket))
        if raw is None:
            return None
        try:
            user_id = int(raw)
        except (TypeError, ValueError):
            return None
        return get_user_model().objects.filter(pk=user_id).first()
