from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from app.constants import FAILURE_STOP_REASONS
from app.exceptions import AgentServiceError, SchemaValidationError
from app.loop.agent_loop import AgentLoop
from app.loop.stop_policy import MaxIterAndNoToolCalls
from app.output.schema import ValidationOutcome, add_usage, validate_output
from app.tools.registry import ToolRegistry
from app.tools.system_tools.structured_output import ANSWER_TOOL, build_answer_tool
from shared.models.agent_service import TokenUsage


@dataclass(frozen=True)
class EnforcementResult:
    """Outcome of ``StructuredOutputEnforcer.enforce()``.

    Carries the parsed answer plus the token usage, iterations, and tool
    invocations accumulated across every retry attempt the enforcer drove
    internally, so callers can fold them into the final ``LoopResult``.
    """

    parsed: dict
    token_usage: TokenUsage
    iterations: int
    tool_invocations: int


class StructuredOutputEnforcer:
    def __init__(self, loop: AgentLoop, max_retries: int) -> None:
        self._loop = loop
        self._max_retries = max_retries

    async def enforce(self, context, output_schema: dict, emitter) -> EnforcementResult:
        usage = TokenUsage()
        iterations = 0
        tool_invocations = 0
        corrective = "Call submit_final_answer with your final answer matching the required schema."

        for attempt in range(self._max_retries + 1):
            spec, capture, wrapped = build_answer_tool(output_schema)
            registry = ToolRegistry()
            registry.register(spec, capture)
            context.tool_choice = {
                "type": "function",
                "function": {"name": ANSWER_TOOL},
            }
            context.append_message({"role": "user", "content": corrective})

            result = await self._loop.run(
                context, registry, emitter, MaxIterAndNoToolCalls(max_iter=1)
            )
            usage = add_usage(usage, result.token_usage)
            iterations += result.iterations
            tool_invocations += result.tool_invocations

            if result.stop_reason in FAILURE_STOP_REASONS:
                context.tool_choice = None
                raise AgentServiceError(
                    result.error
                    or f"agent loop failed ({result.stop_reason}) during schema enforcement"
                )

            if capture.args is None:
                logger.debug(
                    "schema_enforce attempt={} correlation_id={} capture=None",
                    attempt,
                    context.correlation_id,
                )
                corrective = "You must call submit_final_answer. " + corrective
                continue

            candidate = capture.args["result"] if wrapped else capture.args
            outcome: ValidationOutcome = validate_output(candidate, output_schema)

            if outcome.ok:
                logger.debug(
                    "schema_enforce attempt={} correlation_id={} ok=True",
                    attempt,
                    context.correlation_id,
                )
                context.tool_choice = None
                return EnforcementResult(
                    parsed=candidate,
                    token_usage=usage,
                    iterations=iterations,
                    tool_invocations=tool_invocations,
                )

            logger.debug(
                "schema_enforce attempt={} correlation_id={} ok=False error={}",
                attempt,
                context.correlation_id,
                outcome.error,
            )
            corrective = (
                f"Your answer did not match the schema: {outcome.error}. "
                "Call submit_final_answer again with corrected arguments."
            )

        context.tool_choice = None
        raise SchemaValidationError(
            f"output did not satisfy schema after {self._max_retries} retries"
        )
