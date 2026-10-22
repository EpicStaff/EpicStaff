import hashlib
import json
import secrets

from application.ports import AbstractTickets
from redis.asyncio import Redis

PREFIX = "chat:ticket:"


def ticket_digest(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


class RedisTickets(AbstractTickets):
    """Same scheme as Django's SSE tickets: digest as the key, GETDEL on use."""

    def __init__(self, redis: Redis, ttl_seconds: int):
        self._redis = redis
        self._ttl = ttl_seconds

    async def issue(self, payload: dict) -> tuple[str, int]:
        ticket = secrets.token_urlsafe(32)
        await self._redis.set(PREFIX + ticket_digest(ticket), json.dumps(payload), ex=self._ttl)
        return ticket, self._ttl

    async def consume(self, ticket: str) -> dict | None:
        raw = await self._redis.getdel(PREFIX + ticket_digest(ticket))
        return json.loads(raw) if raw else None
