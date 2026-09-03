import secrets
from typing import Optional, Tuple

from django.conf import settings
from django.contrib.auth import get_user_model
from django_redis import get_redis_connection


class PasswordChangeTicketService:
    """Single-use, short-lived tickets that authorize the second step of
    a password change. Issued after the caller proves they know the
    current password; consumed atomically on confirm.

    State lives in Redis and is read/written via the raw `django-redis`
    client so consume can use `GETDEL` (Redis 6.2+) for atomic
    get-and-delete. Without that, a parallel pair of consumers could both
    pass the GET check before either DEL ran, breaking the single-use
    contract.

    Single-purpose by design: a future "email change" or other sudo-mode
    op gets its own dedicated *TicketService, not a `purpose` parameter
    here.
    """

    CACHE_PREFIX = "rbac:password_change_ticket:"

    @property
    def ttl_seconds(self) -> int:
        return settings.PASSWORD_CHANGE_TICKET_TTL
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
