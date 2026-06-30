from __future__ import annotations

import json

from loguru import logger

from app.constants import FAILURE_STOP_REASONS
from app.emitters.base import Emitter
from app.enums import EmitterMode, RunType
from app.exceptions import AgentServiceError
from app.logging_utils import redact
from app.loop.stop_policy import MaxIterAndNoToolCalls
from app.output.enforcer import StructuredOutputEnforcer
from app.output.schema import add_usage
from app.prompt.single_task import SingleTaskPromptBuilder
from app.runners.base import Runner
from shared.models.agent_service import AgentRequest, AgentSpec, LoopResult


def _default_max_iter() -> int:
    from settings import load_settings

    return load_settings().agent_default_max_iter


def _schema_max_retries() -> int:
    from settings import load_settings

    return load_settings().agent_schema_max_retries


class SingleTaskRunner(Runner):
    """Canonical Controller for RunType.SINGLE_TASK: resolve -> build prompt -> run loop -> emit.

    Sole owner of the emitter lifecycle (on_start -> on_final | on_error).
    """

    run_type = RunType.SINGLE_TASK
    emitter_mode = EmitterMode.BATCH
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

            max_iter = agent.max_iter or _default_max_iter()
            logger.debug("stop cap max_iter={}", max_iter)

            has_tools = bool(resolved.tools.tool_specs())

            if output_schema and not has_tools:
                enforcer = StructuredOutputEnforcer(
                    self._deps.loop, _schema_max_retries()
                )
                parsed, usage = await enforcer.enforce(
                    resolved.context, output_schema, emitter
                )
                result = LoopResult(
                    final_text=json.dumps(parsed),
                    tool_invocations=0,
                    iterations=1,
                    stop_reason="schema_satisfied",
                    token_usage=usage,
                )
            else:
                stop = MaxIterAndNoToolCalls(max_iter)
                result = await self._deps.loop.run(
                    resolved.context, resolved.tools, emitter, stop
                )
                if output_schema and result.stop_reason in FAILURE_STOP_REASONS:
                    raise AgentServiceError(
                        result.error or f"agent loop failed ({result.stop_reason})"
                    )

                if output_schema:
                    enforcer = StructuredOutputEnforcer(
                        self._deps.loop, _schema_max_retries()
                    )
                    parsed, usage = await enforcer.enforce(
                        resolved.context, output_schema, emitter
                    )
                    result = result.model_copy(
                        update={
                            "final_text": json.dumps(parsed),
                            "token_usage": add_usage(result.token_usage, usage),
                            "stop_reason": "schema_satisfied",
                        }
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

    def _select_agent(self, request: AgentRequest) -> AgentSpec:
        if not request.agents:
            raise AgentServiceError("SINGLE_TASK request has no agents")

        if len(request.agents) > 1:
            logger.warning(
                "SINGLE_TASK request carries {} agents; using the first",
                len(request.agents),
            )

        return request.agents[0]

    def _parse_payload(self, payload: dict) -> tuple[str, dict | None]:
        instructions = payload.get("task_instructions") or payload.get("prompt")

        if not instructions:
            raise AgentServiceError("SINGLE_TASK payload missing 'task_instructions'")

        return instructions, payload.get("output_schema")
