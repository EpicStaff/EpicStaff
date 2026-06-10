from loguru import logger

from infrastructure.messaging.redis_service import RedisService


class PresenceRepository:
    """Thin Redis adapter for the presence SET per flow.

    Key schema: ``presence:flow:{flow_id}``
    Members:    per-connection UUID4 hex strings
    """

    def __init__(self, redis_service: RedisService) -> None:
        self._redis = redis_service

    def _key(self, flow_id: int) -> str:
        return f"presence:flow:{flow_id}"

    async def add_member(self, flow_id: int, member_id: str) -> None:
        """SADD member_id to the flow's presence set."""
        await self._redis.aioredis_client.sadd(self._key(flow_id), member_id)
        logger.debug("presence SADD flow={} member={}", flow_id, member_id)

    async def remove_member(self, flow_id: int, member_id: str) -> None:
        """SREM member_id from the flow's presence set."""
        await self._redis.aioredis_client.srem(self._key(flow_id), member_id)
        logger.debug("presence SREM flow={} member={}", flow_id, member_id)

    async def count(self, flow_id: int) -> int:
        """Return SCARD (number of live connections) for a flow."""
        result = await self._redis.aioredis_client.scard(self._key(flow_id))
        return int(result)
