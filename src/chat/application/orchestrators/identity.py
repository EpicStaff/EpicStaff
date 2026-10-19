import hashlib
import time
from dataclasses import dataclass

from domain.errors import InvalidTokenError, NotFoundError, NotMemberError
from litestar.exceptions import ClientException

from application.ports import AbstractIdentityProvider


@dataclass(frozen=True)
class Operator:
    user_id: int
    org_id: int
    is_superadmin: bool
    actions: frozenset[str]
    # Shown to other operators of the org, never to visitors; None when EpicStaff sent none.
    display_name: str | None = None

    def allows(self, action: str) -> bool:
        return action in self.actions

    def allows_any(self, actions: tuple[str, ...]) -> bool:
        return not self.actions.isdisjoint(actions)


class OperatorIdentity:
    """Who an EpicStaff user is in the org they name, cached per token hash for `cache_seconds`."""

    def __init__(self, provider: AbstractIdentityProvider, cache_seconds: int):
        self._provider = provider
        self._ttl = cache_seconds
        self._cache: dict[tuple[str, int], tuple[float, Operator]] = {}

    async def resolve(self, jwt: str | None, org_header: str | None) -> Operator:
        """401 for a bad token, 400 for a missing org header, 404 when the org is not the user's."""
        if not jwt:
            raise InvalidTokenError("Bearer token required.")
        if not org_header or not (org_header.isascii() and org_header.isdigit()):
            raise ClientException("X-Organization-Id header is required.")
        org_id = int(org_header)
        key = (hashlib.sha256(jwt.encode("utf-8")).hexdigest(), org_id)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and cached[0] > now:
            return cached[1]
        user = await self._provider.introspect(jwt)
        if user is None:
            raise InvalidTokenError()
        if not user.is_superadmin and org_id not in user.org_ids:
            raise NotFoundError()
        try:
            actions = await self._provider.chats_actions(jwt, org_id)
        except NotMemberError as error:
            raise NotFoundError() from error
        operator = Operator(
            user_id=user.user_id,
            org_id=org_id,
            is_superadmin=user.is_superadmin,
            actions=frozenset(actions),
            display_name=user.display_name,
        )
        self._cache[key] = (now + self._ttl, operator)
        if len(self._cache) > 10_000:
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
        return operator
