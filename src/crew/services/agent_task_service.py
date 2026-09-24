"""
AgentTaskService — delegates TaskNode execution to the ``src/agent``
microservice's ``SingleTaskRunner`` over Redis Streams.

Protocol (see src/agent/tests/test_contract.py):
1. SET the fully-hydrated ``AgentRequest`` JSON (without ``correlation_id``)
   at key ``agent:request:<uuid>``.
2. XADD a ``StreamEnvelope{type: "agent.run", correlation_id, payload:
   {"request_key"}}`` to ``agent.requests``.
3. Await the result on the run's own stream
   ``agent_result_stream(result_stream_prefix, correlation_id)`` (e.g.
   ``agent.results:<uuid>``): an ``agent.result`` or ``agent.error``
   envelope ends the wait. Along the way, live envelopes whose ``type`` is
   in ``LIVE_EVENT_TYPES`` (currently ``agent.tool_call`` /
   ``agent.tool_result`` / ``agent.task_start`` / ``agent.task_finish`` /
   ``agent.knowledge_search``) are forwarded to the caller's ``on_event``
   callback; envelopes of any other type are skipped.
4. DELETE the request key and the per-run stream once the wait ends, however
   it ends. The agent sets a TTL on the stream at every publish, so a stream
   left behind by a crashed crew — or recreated by a late agent publish after
   crew gave up — still expires.

One stream per run keeps runs of different organizations out of each
other's reads by construction: a waiter never receives, parses, or has to
filter out another run's payload. Consumption is a plain ``XREAD`` from
``"0"`` — the stream is new and private to this run, so no tail offset is
needed, and no consumer group, which would only add ack bookkeeping for a
single reader.
"""

import json
import time
import uuid
from collections.abc import Callable

from loguru import logger
from services.graph.events import StopEvent
from services.redis_service import RedisService
from src.shared.models import AgentDefinitionData, AgentNodeData, TaskNodeData
from src.shared.models.agent_service import (
    FAILURE_STOP_REASONS,
    AgentRequest,
    AgentSpec,
    AgentTaskSpec,
    RunType,
)
from src.shared.redis_streams import StreamEnvelope, agent_result_stream

LIVE_EVENT_TYPES = frozenset(
    {
        "agent.tool_call",
        "agent.tool_result",
        "agent.task_start",
        "agent.task_finish",
        "agent.knowledge_search",
    }
)
"""Envelope types forwarded live to ``on_event`` instead of ending the wait."""


class AgentTaskError(Exception): ...


class AgentTaskTimeoutError(AgentTaskError): ...


class AgentTaskService:
    def __init__(
        self,
        redis_service: RedisService,
        request_stream: str = "agent.requests",
        result_stream_prefix: str = "agent.results",
        default_timeout: float = 600.0,
        timeout_buffer_s: float = 60.0,
        poll_block_ms: int = 1000,
        request_key_ttl_s: int = 86400,
    ):
        self.redis_service = redis_service
        self.request_stream = request_stream
        self.result_stream_prefix = result_stream_prefix
        self.default_timeout_s = default_timeout
        self.timeout_buffer_s = timeout_buffer_s
        self.poll_block_ms = poll_block_ms
        self.request_key_ttl_s = request_key_ttl_s

    async def run_task(
        self,
        node_data: TaskNodeData,
        stop_event: StopEvent,
        on_event: Callable[[StreamEnvelope], None] | None = None,
    ) -> dict:
        blob = self._build_request_blob(node_data)
        timeout_s = self._resolve_timeout_s(node_data.agent_definition)
        return await self._dispatch(blob, timeout_s, stop_event, on_event)

    async def run_agent_node(
        self,
        agent_node_data: AgentNodeData,
        stop_event: StopEvent,
        on_event: Callable[[StreamEnvelope], None] | None = None,
    ) -> dict:
        blob = self._build_agent_node_request_blob(agent_node_data)
        task_count = len(agent_node_data.tasks)
        timeout_s = self._resolve_timeout_s(agent_node_data.agent_definition, task_count=task_count)
        return await self._dispatch(blob, timeout_s, stop_event, on_event)

    async def _dispatch(
        self,
        blob: str,
        timeout_s: float,
        stop_event: StopEvent,
        on_event: Callable[[StreamEnvelope], None] | None = None,
    ) -> dict:
        client = self.redis_service.aioredis_client
        correlation_id = str(uuid.uuid4())
        request_key = f"agent:request:{correlation_id}"
        result_stream = agent_result_stream(self.result_stream_prefix, correlation_id)

        await client.set(request_key, blob, ex=self.request_key_ttl_s)

        envelope = StreamEnvelope(
            type="agent.run",
            correlation_id=correlation_id,
            payload={"request_key": request_key},
        )
        await client.xadd(self.request_stream, envelope.to_fields())
        logger.info("published agent.run correlation_id={}", correlation_id)

        deadline = time.monotonic() + timeout_s

        try:
            return await self._await_result(
                client=client,
                correlation_id=correlation_id,
                result_stream=result_stream,
                deadline=deadline,
                stop_event=stop_event,
                on_event=on_event,
            )
        finally:
            await client.delete(request_key, result_stream)

    def _resolve_timeout_s(
        self, agent_definition: AgentDefinitionData | None, task_count: int = 1
    ) -> float:
        max_execution_time = agent_definition.max_execution_time if agent_definition else None
        if max_execution_time is not None:
            return max_execution_time * task_count + self.timeout_buffer_s
        return self.default_timeout_s * task_count

    async def _await_result(
        self,
        client,
        correlation_id: str,
        result_stream: str,
        deadline: float,
        stop_event: StopEvent,
        on_event: Callable[[StreamEnvelope], None] | None = None,
    ) -> dict:
        last_id = "0"
        while True:
            stop_event.check_stop()

            remaining_s = deadline - time.monotonic()
            if remaining_s <= 0:
                raise AgentTaskTimeoutError(
                    f"Timed out waiting for agent result, correlation_id={correlation_id}"
                )

            block_ms = min(self.poll_block_ms, max(int(remaining_s * 1000), 1))
            response = await client.xread({result_stream: last_id}, block=block_ms)
            if not response:
                continue

            for _stream_name, entries in response:
                for message_id, fields in entries:
                    last_id = message_id
                    envelope = StreamEnvelope.from_fields(fields)

                    if envelope.type in LIVE_EVENT_TYPES:
                        if on_event is not None:
                            try:
                                on_event(envelope)
                            except Exception:
                                logger.warning(
                                    "on_event callback failed correlation_id={} type={}",
                                    correlation_id,
                                    envelope.type,
                                )
                        continue

                    if envelope.type == "agent.error":
                        raise AgentTaskError(envelope.payload.get("error", "agent error"))

                    if envelope.type == "agent.result":
                        stop_reason = envelope.payload.get("stop_reason")
                        if stop_reason in FAILURE_STOP_REASONS:
                            raise AgentTaskError(
                                envelope.payload.get("error") or f"agent stop_reason={stop_reason}"
                            )
                        return envelope.payload

    def _build_agent_spec(
        self,
        agent_definition: AgentDefinitionData,
        surface_instructions: str,
        tools,
        collections,
        s3_files,
    ) -> AgentSpec:
        instructions = agent_definition.instructions
        if surface_instructions:
            instructions = f"{instructions}\n\n{surface_instructions}"

        return AgentSpec(
            id=agent_definition.id,
            name=agent_definition.name,
            instructions=instructions,
            llm=agent_definition.llm,
            fcm_llm=agent_definition.fcm_llm,
            max_iter=agent_definition.max_iter,
            schema_max_retries=agent_definition.schema_max_retries,
            max_rpm=agent_definition.max_rpm,
            max_execution_time=agent_definition.max_execution_time,
            cache=agent_definition.cache,
            max_retry_limit=agent_definition.max_retry_limit,
            default_temperature=agent_definition.default_temperature,
            max_tool_calls=agent_definition.max_tool_calls,
            tool_timeout=agent_definition.tool_timeout,
            max_consecutive_failures=agent_definition.max_consecutive_failures,
            tool_refs=[tool.unique_name for tool in tools],
            collection_refs=[collection.unique_name for collection in collections],
            s3_refs=[s3_file.id for s3_file in s3_files],
        )

    def _build_request_blob(self, node_data: TaskNodeData) -> str:
        agent_definition = node_data.agent_definition

        agent_spec = self._build_agent_spec(
            agent_definition,
            node_data.surface.instructions,
            node_data.tools,
            node_data.collections,
            node_data.s3_files,
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

    def _build_agent_node_request_blob(self, agent_node_data: AgentNodeData) -> str:
        agent_definition = agent_node_data.agent_definition

        agent_spec = self._build_agent_spec(
            agent_definition,
            agent_node_data.surface.instructions,
            agent_node_data.tools,
            agent_node_data.collections,
            agent_node_data.s3_files,
        )

        payload = {
            "tasks": [
                AgentTaskSpec(
                    name=task.name,
                    instructions=task.instructions,
                    output_schema=task.output_schema or None,
                    context=task.context_tasks,
                ).model_dump()
                for task in agent_node_data.tasks
            ]
        }

        request = AgentRequest(
            correlation_id="unused",
            run_type=RunType.LIST_OF_TASKS,
            agents=[agent_spec],
            tools=agent_node_data.tools,
            collections=agent_node_data.collections,
            s3_files=agent_node_data.s3_files,
            payload=payload,
        )
        dumped = request.model_dump(mode="json", exclude={"correlation_id"})
        return json.dumps(dumped)
