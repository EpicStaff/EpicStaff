"""Publishes finished executions to Redis for the producers to consume.

Results go to the result channel in the shape the existing consumers already read
(``result_data``/``stdout``/``stderr``/``returncode``), so no consumer-side change is
needed. A result whose job asked for it goes to crew's own result channel instead, so
crew never has to sift through results meant for django_app, agent or realtime. Both
channel names are configured here from the sandbox's own settings, never taken from a
submission. Storage mutations, when present, go to their own channel as the mutation
event the storage consumer expects, whichever result channel was used.
"""

import json

from common.contracts import ExecutionResultMessage
from redis.asyncio import Redis

from manager.infrastructure.transport.result_publisher import AbstractResultPublisher

__all__ = ["RedisResultPublisher"]


class RedisResultPublisher(AbstractResultPublisher):
    def __init__(
        self,
        redis: Redis,
        *,
        result_channel: str,
        crew_result_channel: str,
        mutation_channel: str,
    ):
        self._redis = redis
        self._result_channel = result_channel
        self._crew_result_channel = crew_result_channel
        self._mutation_channel = mutation_channel

    async def publish(self, result: ExecutionResultMessage) -> None:
        payload = {
            "execution_id": result.execution_id,
            "result_data": result.result,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
        channel = (
            self._crew_result_channel if result.reply_to_crew_channel else self._result_channel
        )
        await self._redis.publish(channel, json.dumps(payload))

        if result.mutations is not None and result.mutations.mutations:
            event = {
                "execution_id": result.execution_id,
                "org_prefix": result.mutations.org_prefix,
                "session_id": result.mutations.session_id,
                "mutations": result.mutations.mutations,
            }
            await self._redis.publish(self._mutation_channel, json.dumps(event))
