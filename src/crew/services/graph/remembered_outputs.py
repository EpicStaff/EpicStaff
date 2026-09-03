import json

import settings
from services.redis_service import RedisService


class RememberedOutputsStore:
    """Session-scoped Redis store for outputs of task nodes with remember_output=True.

    Key: session:{session_id}:remembered_outputs — Redis LIST of JSON entries
    {"node": <node_name>, "output": <final_text>}. Writes are a single atomic
    RPUSH (safe under parallel LangGraph branches); reads deduplicate by node
    name keeping the LATEST output in FIRST-SEEN order (re-execution in cyclic
    flows overwrites the value but keeps the position).
    """

    def __init__(self, redis_service: RedisService, ttl_s: int = settings.REMEMBERED_OUTPUTS_TTL):
        self._redis_service = redis_service
        self._ttl_s = ttl_s

    @staticmethod
    def _key(session_id: int) -> str:
        return f"session:{session_id}:remembered_outputs"

    async def store(self, session_id: int, node_name: str, output: str) -> None:
        r = self._redis_service.aioredis_client
        key = self._key(session_id)
        await r.rpush(key, json.dumps({"node": node_name, "output": output}))
        await r.expire(key, self._ttl_s)

    async def fetch_all(self, session_id: int) -> list[tuple[str, str]]:
        r = self._redis_service.aioredis_client
        raw_entries = await r.lrange(self._key(session_id), 0, -1)
        deduped: dict[str, str] = {}
        for raw in raw_entries:
            entry = json.loads(raw)
            deduped[entry["node"]] = entry["output"]
        return list(deduped.items())

    async def clear(self, session_id: int) -> None:
        await self._redis_service.aioredis_client.delete(self._key(session_id))


def format_remembered_outputs_preamble(outputs: list[tuple[str, str]]) -> str:
    """Mirror of format_context_preamble in src/agent/app/runners/list_of_tasks.py
    (LIST_OF_TASKS pattern) — keep the delimiter format in sync manually."""
    if not outputs:
        return ""
    blocks = [f"Task '{name}':\n{output}" for name, output in outputs]
    joined_blocks = "\n\n".join(blocks)
    return (
        "===== PREVIOUS TASKS OUTPUTS =====\n\n"
        f"{joined_blocks}\n\n"
        "===== END PREVIOUS TASKS OUTPUTS =====\n\n"
    )
