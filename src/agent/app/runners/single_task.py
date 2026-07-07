from __future__ import annotations

from loguru import logger

from app.emitters.base import Emitter
from app.enums import EmitterMode, RunType
from app.exceptions import AgentServiceError
from app.logging_utils import redact
from app.prompt.single_task import SingleTaskPromptBuilder
from app.runners.base import Runner
from app.runners.task_execution import (
    _default_max_iter,
    _schema_max_retries,
    run_task_through_loop,
)
from shared.models.agent_service import AgentRequest


class SingleTaskRunner(Runner):
    """Canonical Controller for RunType.SINGLE_TASK: resolve -> build prompt -> run loop -> emit.

    Sole owner of the emitter lifecycle (on_start -> on_final | on_error).
    """

    run_type = RunType.SINGLE_TASK
    emitter_mode = EmitterMode.TOOL_EVENTS
    _prompt_builder = SingleTaskPromptBuilder()

    async def execute(self, request: AgentRequest, emitter: Emitter) -> None:
        await emitter.on_start(request)

        try:
            agent = self._select_agent(request)
            logger.info(
                "single_task start correlation_id={} agent_id={}",
                request.correlation_id,
                agent.id,
            )
            logger.debug(
                "agent name={} provider={} model={} max_iter={} tools={} rags={} s3={}",
                agent.name,
                agent.llm.provider,
                agent.llm.config.model,
                agent.max_iter,
                len(agent.tool_refs),
                len(agent.collection_refs),
                len(agent.s3_refs),
            )

            instructions, output_schema = self._parse_payload(request.payload)
            logger.debug(
                "task instructions={!r} has_output_schema={}",
                instructions,
                output_schema is not None,
            )

            if output_schema:
                logger.opt(lazy=True).debug("output_schema={}", lambda: output_schema)

            resolved = await self._deps.resolver.resolve(agent, request)
            logger.debug(
                "resolved tools={} attachments={}",
                [s.name for s in resolved.tools.tool_specs()],
                len(resolved.attachments),
            )

            messages = self._prompt_builder.build(
                agent,
                instructions=instructions,
                output_schema=output_schema,
                attachments=resolved.attachments,
            )
            _corr_id = request.correlation_id
            logger.opt(lazy=True).debug(
                "prompt messages correlation_id={} messages={}",
                lambda: _corr_id,
                lambda: redact(messages),
            )

            for message in messages:
                resolved.context.append_message(message)

            result = await run_task_through_loop(
                self._deps,
                agent,
                resolved.context,
                resolved.tools,
                output_schema,
                emitter,
                max_iter_fn=_default_max_iter,
                schema_max_retries_fn=_schema_max_retries,
            )

            logger.info(
                "single_task done correlation_id={} stop_reason={} iterations={} tool_invocations={}",
                request.correlation_id,
                result.stop_reason,
                result.iterations,
                result.tool_invocations,
            )
            _corr_id_final = request.correlation_id
            logger.opt(lazy=True).debug(
                "final_text correlation_id={} text={!r}",
                lambda: _corr_id_final,
                lambda: result.final_text,
            )
            await emitter.on_final(result)

        except AgentServiceError as error:
            logger.error(
                "single_task failed correlation_id={} error={}",
                request.correlation_id,
                error,
            )
            await emitter.on_error(
                error
            )  # expected domain failure → agent.error; do NOT re-raise

        except Exception as error:
            logger.exception(
                "single_task crashed correlation_id={}", request.correlation_id
            )
            await emitter.on_error(
                error
            )  # unexpected failure → agent.error; do NOT re-raise

    def _parse_payload(self, payload: dict) -> tuple[str, dict | None]:
        instructions = payload.get("task_instructions") or payload.get("prompt")

        if not instructions:
            raise AgentServiceError("SINGLE_TASK payload missing 'task_instructions'")

        return instructions, payload.get("output_schema")
