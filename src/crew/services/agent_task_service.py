"""
AgentTaskService — delegates TaskNode execution to the ``src/agent``
microservice's ``SingleTaskRunner`` over Redis Streams.

Protocol (see src/agent/tests/test_contract.py):
1. SET the fully-hydrated ``AgentRequest`` JSON (without ``correlation_id``)
   at key ``agent:request:<uuid>``.
2. XADD a ``StreamEnvelope{type: "agent.run", correlation_id, payload:
   {"request_key"}}`` to ``agent.requests``.
3. Await the matching result on ``agent.results``: ``agent.result`` payload
   or ``agent.error`` payload, both keyed by ``correlation_id``.

Consumption is a plain ``XREAD`` from a private pre-publish tail offset,
NOT a consumer group — consumer groups compete-consume, so concurrent task
nodes would steal each other's results. Every waiter sees all results and
filters by ``correlation_id``, mirroring ``RunPythonCodeService``'s
per-call subscribe pattern but with server-side blocking.
"""

import json
import time
import uuid

from loguru import logger

from services.graph.events import StopEvent
from services.redis_service import RedisService
from src.shared.models import TaskNodeData
from src.shared.models.agent_service import AgentRequest, AgentSpec, RunType
from src.shared.redis_streams import StreamEnvelope

FAILURE_STOP_REASONS = frozenset({"llm_error", "timeout"})
"""Stop reasons that indicate a hard agent-loop failure; mirrors src/agent/app/constants.py."""


class AgentTaskError(Exception): ...


class AgentTaskTimeoutError(AgentTaskError): ...


class AgentTaskService:
    def __init__(
        self,
        redis_service: RedisService,
        request_stream: str = "agent.requests",
        result_stream: str = "agent.results",
        default_timeout_s: float = 600.0,
        timeout_buffer_s: float = 60.0,
        poll_block_ms: int = 1000,
        request_key_ttl_s: int = 86400,
    ):
        self.redis_service = redis_service
        self.request_stream = request_stream
        self.result_stream = result_stream
        self.default_timeout_s = default_timeout_s
        self.timeout_buffer_s = timeout_buffer_s
        self.poll_block_ms = poll_block_ms
        self.request_key_ttl_s = request_key_ttl_s

    async def run_task(self, node_data: TaskNodeData, stop_event: StopEvent) -> dict:
        client = self.redis_service.aioredis_client
        correlation_id = str(uuid.uuid4())
        request_key = f"agent:request:{correlation_id}"

        last_id = await self._tail_result_id(client)
        blob = self._build_request_blob(node_data)
        await client.set(request_key, blob, ex=self.request_key_ttl_s)

        envelope = StreamEnvelope(
            type="agent.run",
            correlation_id=correlation_id,
            payload={"request_key": request_key},
        )
        await client.xadd(self.request_stream, envelope.to_fields())
        logger.info("published agent.run correlation_id={}", correlation_id)

        deadline = time.monotonic() + self._resolve_timeout_s(node_data)

        try:
            return await self._await_result(
                client=client,
                correlation_id=correlation_id,
                last_id=last_id,
                deadline=deadline,
                stop_event=stop_event,
            )
        finally:
            await client.delete(request_key)

    def _resolve_timeout_s(self, node_data: TaskNodeData) -> float:
        agent_definition = node_data.agent_definition
        max_execution_time = (
            agent_definition.max_execution_time if agent_definition else None
        )
        if max_execution_time is not None:
            return max_execution_time + self.timeout_buffer_s
        return self.default_timeout_s

    async def _tail_result_id(self, client) -> str:
        entries = await client.xrevrange(self.result_stream, count=1)
        if not entries:
            return "0"
        latest_id, _fields = entries[0]
        return latest_id

    async def _await_result(
        self,
        client,
        correlation_id: str,
        last_id: str,
        deadline: float,
        stop_event: StopEvent,
    ) -> dict:
        while True:
            stop_event.check_stop()

            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                raise AgentTaskTimeoutError(
                    f"Timed out waiting for agent result, correlation_id={correlation_id}"
                )

            block_ms = min(self.poll_block_ms, max(int(remaining_s * 1000), 1))
            response = await client.xread({self.result_stream: last_id}, block=block_ms)
            if not response:
                continue

            for _stream_name, entries in response:
                for message_id, fields in entries:
                    last_id = message_id
                    envelope = StreamEnvelope.from_fields(fields)
                    if envelope.correlation_id != correlation_id:
                        continue

                    if envelope.type == "agent.error":
                        raise AgentTaskError(
                            envelope.payload.get("error", "agent error")
                        )

                    if envelope.type == "agent.result":
                        stop_reason = envelope.payload.get("stop_reason")
                        if stop_reason in FAILURE_STOP_REASONS:
                            raise AgentTaskError(
                                envelope.payload.get("error")
                                or f"agent stop_reason={stop_reason}"
                            )
                        return envelope.payload

    def _build_request_blob(self, node_data: TaskNodeData) -> str:
        agent_definition = node_data.agent_definition

        instructions = agent_definition.instructions
        if node_data.surface.instructions:
            instructions = f"{instructions}\n\n{node_data.surface.instructions}"

        agent_spec = AgentSpec(
            id=agent_definition.id,
            name=agent_definition.name,
            instructions=instructions,
            llm=agent_definition.llm,
            fcm_llm=agent_definition.fcm_llm,
            max_iter=agent_definition.max_iter,
            max_rpm=agent_definition.max_rpm,
            max_execution_time=agent_definition.max_execution_time,
            cache=agent_definition.cache,
            max_retry_limit=agent_definition.max_retry_limit,
            default_temperature=agent_definition.default_temperature,
            tool_refs=[tool.unique_name for tool in node_data.tools],
            collection_refs=[
                collection.unique_name for collection in node_data.collections
            ],
            s3_refs=[s3_file.id for s3_file in node_data.s3_files],
        )

        payload = {"task_instructions": node_data.instructions}
        if node_data.output_schema:
            payload["output_schema"] = node_data.output_schema

        request = AgentRequest(
            correlation_id="unused",
            run_type=RunType.SINGLE_TASK,
            agents=[agent_spec],
            tools=node_data.tools,
            collections=node_data.collections,
            s3_files=node_data.s3_files,
            payload=payload,
        )
        dumped = request.model_dump(mode="json", exclude={"correlation_id"})
        return json.dumps(dumped)
