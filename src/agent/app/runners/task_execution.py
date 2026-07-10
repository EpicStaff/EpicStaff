"""
Shared task-execution helper: runs one prompt through ``AgentLoop`` and
applies structured-output enforcement if the task declares an
``output_schema``.

Extracted from ``SingleTaskRunner`` so ``ListOfTasksRunner`` can reuse the
exact same enforcer/loop/enforce sequencing for each task in its list
without duplicating the branching logic.
"""

from __future__ import annotations

import json

from app.constants import FAILURE_STOP_REASONS
from app.emitters.base import Emitter
from app.exceptions import AgentServiceError
from app.loop.context import AgentContext
from app.loop.stop_policy import MaxIterAndNoToolCalls
from app.output.enforcer import StructuredOutputEnforcer
from app.output.schema import add_usage, as_object_schema
from app.runners.deps import RunnerDependencies
from app.tools.registry import ToolRegistry
from shared.models.agent_service import AgentSpec, LoopResult, StopReason


def _default_max_iter() -> int:
    from settings import load_settings

    return load_settings().agent_default_max_iter


def _schema_max_retries() -> int:
    from settings import load_settings

    return load_settings().agent_schema_max_retries


async def run_task_through_loop(
    deps: RunnerDependencies,
    agent: AgentSpec,
    context: AgentContext,
    tools: ToolRegistry,
    output_schema: dict | None,
    emitter: Emitter,
    *,
    max_iter_fn=_default_max_iter,
    schema_max_retries_fn=_schema_max_retries,
) -> LoopResult:
    """Run ``context`` through ``deps.loop``, enforcing ``output_schema`` if given.

    If ``output_schema`` is set, its shape is validated upfront via
    ``as_object_schema`` before any LLM call — an unrecognizable schema
    (non-dict, or missing a top-level "type") raises
    ``InvalidOutputSchemaError`` immediately instead of burning loop
    iterations first.

    Mirrors the original inline logic in ``SingleTaskRunner.execute``:
    - if there is an ``output_schema`` and no tools, skip the plain loop and
      go straight to the enforcer (which drives its own single-turn loop
      calls internally).
    - otherwise run the plain loop first; if it fails (a stop_reason in
      ``FAILURE_STOP_REASONS``) while an ``output_schema`` was requested,
      raise ``AgentServiceError`` without ever invoking the enforcer.
    - if an ``output_schema`` was requested and the plain loop succeeded,
      enforce it and fold the enforcer's usage into the plain loop's result.

    ``max_iter_fn`` / ``schema_max_retries_fn`` are injected (defaulting to
    the module-level settings loaders) so callers can pass their own
    module-bound references, which keeps ``unittest.mock.patch`` targeting
    the calling runner's module working as expected.
    """
    max_iter = agent.max_iter or max_iter_fn()
    has_tools = bool(tools.tool_specs())
    schema_retries: int | None = None

    if output_schema:
        # Fail fast on an unrecognizable schema before any LLM call — the
        # plain loop below can run many iterations/tool calls before ever
        # reaching the enforcer, so this check must happen first.
        as_object_schema(output_schema)
        schema_retries = (
            agent.schema_max_retries
            if agent.schema_max_retries is not None
            else schema_max_retries_fn()
        )

    if output_schema and not has_tools:
        enforcer = StructuredOutputEnforcer(deps.loop, schema_retries)
        parsed, usage = await enforcer.enforce(context, output_schema, emitter)
        return LoopResult(
            final_text=json.dumps(parsed),
            tool_invocations=0,
            iterations=1,
            stop_reason=StopReason.SCHEMA_SATISFIED.value,
            token_usage=usage,
        )

    stop = MaxIterAndNoToolCalls(max_iter)
    result = await deps.loop.run(context, tools, emitter, stop)

    if output_schema and result.stop_reason in FAILURE_STOP_REASONS:
        raise AgentServiceError(
            result.error or f"agent loop failed ({result.stop_reason})"
        )

    if output_schema:
        enforcer = StructuredOutputEnforcer(deps.loop, schema_retries)
        parsed, usage = await enforcer.enforce(context, output_schema, emitter)
        result = result.model_copy(
            update={
                "final_text": json.dumps(parsed),
                "token_usage": add_usage(result.token_usage, usage),
                "stop_reason": (
                    result.stop_reason
                    if result.stop_reason == StopReason.MAX_CONSECUTIVE_FAILURES.value
                    else StopReason.SCHEMA_SATISFIED.value
                ),
            }
        )

    return result
