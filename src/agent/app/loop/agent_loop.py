"""
AgentLoop ABC and DefaultAgentLoop: single-agent tool-use cycle.

``AgentLoop`` is the only component in the architecture that speaks to
``LLMClient``, accumulates tool calls across chunks, dispatches to
``ToolRegistry``, and checks ``StopPolicy``.  It is deliberately ignorant of
``RunType``; runners decide *how many* times to invoke it.

``DefaultAgentLoop`` is the canonical concrete implementation: one LLM call
per iteration, streaming always enabled, tool errors fed back as
``ToolResult(is_error=True)`` so the model can recover, wall-clock limit
enforced via ``asyncio.wait_for``.
"""

from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass

import litellm
from loguru import logger

from app.emitters.base import Emitter
from app.llm.client import LLMChunk, LLMClient
from app.logging_utils import redact
from app.loop.context import AgentContext
from app.loop.stop_policy import StopPolicy
from app.tools.registry import ToolRegistry
from shared.models.agent_service import LoopResult, StopReason, TokenUsage, ToolResult


def _model_str(context: AgentContext) -> str:
    """Return the fully-qualified model string used by litellm (e.g. 'openai/gpt-4o')."""
    llm = context.agent.llm
    model = llm.config.model
    return model if "/" in model else f"{llm.provider}/{model}"


def _safe_context_window(model_str: str) -> int | None:
    """Return max input tokens for model_str, or None if unavailable."""
    try:
        info = litellm.get_model_info(model_str)
        return info.get("max_input_tokens") or info.get("max_tokens")
    except Exception:
        return None


def _safe_token_count(model_str: str, messages: list[dict]) -> int | None:
    """Return token count for messages, or None if counting fails."""
    try:
        return litellm.token_counter(model=model_str, messages=messages)
    except Exception:
        return None


def _build_model_config(context: AgentContext) -> dict:
    """Build the litellm-compatible model_config dict from the agent's LLM spec.

    Prefixes ``model`` with ``provider/`` when the provider name is not
    already present in the model string (e.g. ``openai/gpt-4o`` vs a model
    that already carries a provider prefix like ``azure/gpt-4o``).
    """
    llm = context.agent.llm
    config = llm.config.model_dump(exclude_none=True)
    config["model"] = _model_str(context)

    if context.tool_choice is not None:
        config["tool_choice"] = context.tool_choice

    return config


class AgentLoop(ABC):
    """Abstract single-agent tool-use cycle.

    One ``run`` call corresponds to one full LLM conversation turn that may
    span multiple iterations (each iteration: call LLM → process chunks →
    execute tools → repeat until ``StopPolicy`` says stop).

    Collaborators: ``AgentContext`` (mutable conversation state),
    ``ToolRegistry`` (tool dispatch), ``Emitter`` (streaming hooks),
    ``StopPolicy`` (termination condition).
    """

    @abstractmethod
    async def run(
        self,
        context: AgentContext,
        tools: ToolRegistry,
        emitter: Emitter,
        stop: StopPolicy,
    ) -> LoopResult:
        """Execute the tool-use cycle and return a summary result."""
        ...


@dataclass
class _RunState:
    """Mutable accumulator for in-progress loop statistics.

    Held outside ``_run_inner`` so a timeout can still return whatever
    progress was made before the cancellation point.
    """

    iterations: int = 0
    tool_invocations: int = 0
    final_text: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_prompt_tokens: int = 0
    context_warned: bool = False
    consecutive_failures: int = 0

    def token_usage(self) -> TokenUsage:
        return TokenUsage(
            prompt_tokens=self.prompt_tokens,
            completion_tokens=self.completion_tokens,
            total_tokens=self.total_tokens,
            cached_prompt_tokens=self.cached_prompt_tokens,
        )

    def add_usage(self, usage: dict) -> None:
        self.prompt_tokens += int(usage.get("prompt_tokens", 0))
        self.completion_tokens += int(usage.get("completion_tokens", 0))
        self.total_tokens += int(
            usage.get(
                "total_tokens",
                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
            )
        )
        self.cached_prompt_tokens += int(usage.get("cached_prompt_tokens", 0))


class DefaultAgentLoop(AgentLoop):
    """Canonical single-agent tool-use loop.

    Drives one LLM conversation turn: stream chunks, accumulate tool calls,
    dispatch tools, feed results back, repeat until ``StopPolicy`` says stop.

    Tool errors (raises, JSON parse failures, unknown names) are coalesced into
    ``ToolResult(is_error=True)`` and fed back to the LLM — they never abort
    the loop.  LLM-level exceptions and wall-clock limit exhaustion terminate
    the loop and return a partial ``LoopResult``.
    """

    def __init__(
        self, llm: LLMClient, context_warning_ratio: float | None = None
    ) -> None:
        self._llm = llm
        self._context_warning_ratio = context_warning_ratio

    async def run(
        self,
        context: AgentContext,
        tools: ToolRegistry,
        emitter: Emitter,
        stop: StopPolicy,
    ) -> LoopResult:
        """Enforce the wall-clock limit and delegate to ``_run_inner``."""
        state = _RunState()
        time_limit = context.agent.max_execution_time

        try:
            if time_limit is None:
                return await self._run_inner(context, tools, emitter, stop, state)

            return await asyncio.wait_for(
                self._run_inner(context, tools, emitter, stop, state),
                timeout=time_limit,
            )

        except asyncio.TimeoutError:
            logger.warning(
                "loop timeout correlation_id={} iterations={}",
                context.correlation_id,
                state.iterations,
            )
            return LoopResult(
                stop_reason=StopReason.TIMEOUT.value,
                final_text=state.final_text,
                tool_invocations=state.tool_invocations,
                iterations=state.iterations,
                token_usage=state.token_usage(),
                error=f"execution exceeded {time_limit}s",
            )

        except Exception as error:
            logger.exception("loop llm_error correlation_id={}", context.correlation_id)
            return LoopResult(
                stop_reason=StopReason.LLM_ERROR.value,
                final_text=state.final_text,
                tool_invocations=state.tool_invocations,
                iterations=state.iterations,
                token_usage=state.token_usage(),
                error=str(error),
            )

    async def _run_inner(
        self,
        context: AgentContext,
        tools: ToolRegistry,
        emitter: Emitter,
        stop: StopPolicy,
        state: _RunState,
    ) -> LoopResult:
        """Core iteration loop — no timeout handling, no exception swallowing."""
        ratio = self._context_warning_ratio
        model_str = _model_str(context)
        context_window = (
            _safe_context_window(model_str) if ratio and ratio > 0 else None
        )

        while True:
            if context_window and ratio and not state.context_warned:
                input_tokens = _safe_token_count(model_str, context.messages)
                if input_tokens is not None and input_tokens >= ratio * context_window:
                    await emitter.on_warning(
                        f"input context >= {int(ratio * 100)}% of model context window "
                        f"({context_window} tokens) for '{model_str}'; approaching limit"
                    )
                    state.context_warned = True

            _iter = state.iterations
            _corr_id = context.correlation_id
            _msg_count = len(context.messages)
            logger.opt(lazy=True).debug(
                "loop iter={} correlation_id={} sending {} messages={}",
                lambda: _iter,
                lambda: _corr_id,
                lambda: _msg_count,
                lambda: redact(context.messages),
            )

            text_buf = ""
            tool_buf: dict[str, dict] = {}
            chunks: list[LLMChunk] = []

            async for chunk in self._llm.chat(
                messages=context.messages,
                tools=tools.tool_specs(),
                model_config=_build_model_config(context),
                stream=True,
                runtime_config={
                    "max_retry_limit": context.agent.max_retry_limit,
                    "max_rpm": context.agent.max_rpm,
                },
            ):
                await emitter.on_chunk(chunk)
                chunks.append(chunk)

                if chunk.delta_text:
                    text_buf += chunk.delta_text

                if chunk.tool_call_fragment:
                    fragment = chunk.tool_call_fragment
                    entry = tool_buf.setdefault(
                        fragment.id, {"name": fragment.name, "args": ""}
                    )
                    entry["args"] += fragment.arguments_delta

                if chunk.usage:
                    state.add_usage(chunk.usage)

            # Only append the assistant message when there is content to record.
            # An iteration with neither text nor tool calls still counts toward
            # the iteration limit; StopPolicy will terminate naturally.
            if text_buf or tool_buf:
                assistant_message: dict = {"role": "assistant"}

                if text_buf:
                    assistant_message["content"] = text_buf
                    state.final_text = text_buf

                if tool_buf:
                    assistant_message["tool_calls"] = [
                        {
                            "id": call_id,
                            "type": "function",
                            "function": {
                                "name": entry["name"],
                                "arguments": entry["args"],
                            },
                        }
                        for call_id, entry in tool_buf.items()
                    ]

                context.append_message(assistant_message)
                logger.debug(
                    "assistant text_len={} tool_calls={}",
                    len(text_buf),
                    [e["name"] for e in tool_buf.values()],
                )

            complete_calls = [
                (call_id, entry["name"], entry["args"])
                for call_id, entry in tool_buf.items()
            ]

            max_tool_calls = context.agent.max_tool_calls
            max_failures = context.agent.max_consecutive_failures
            failure_limit_hit = False

            for index, (call_id, name, args_str) in enumerate(complete_calls):
                await emitter.on_tool_call(
                    {"id": call_id, "name": name, "arguments": args_str}
                )
                logger.debug("tool call id={} name={} args={}", call_id, name, args_str)

                if failure_limit_hit:
                    result = ToolResult(
                        tool_call_id=call_id,
                        content="Tool call not executed: consecutive tool failure limit reached.",
                        is_error=True,
                    )

                elif max_tool_calls is not None and index >= max_tool_calls:
                    result = ToolResult(
                        tool_call_id=call_id,
                        content=(
                            f"Tool call limit reached: at most {max_tool_calls} tool "
                            "call(s) may be executed per turn; this call was not executed."
                        ),
                        is_error=True,
                    )

                else:
                    result = await self._execute_tool(
                        tools,
                        call_id,
                        name,
                        args_str,
                        timeout=context.agent.tool_timeout,
                    )
                    state.tool_invocations += 1

                    if result.is_error:
                        state.consecutive_failures += 1

                    else:
                        state.consecutive_failures = 0

                    if (
                        max_failures is not None
                        and state.consecutive_failures >= max_failures
                    ):
                        failure_limit_hit = True

                logger.debug(
                    "tool result id={} is_error={} content={!r}",
                    call_id,
                    result.is_error,
                    result.content,
                )
                await emitter.on_tool_result(result)
                context.append_message(
                    {"role": "tool", "tool_call_id": call_id, "content": result.content}
                )

            state.iterations += 1

            if failure_limit_hit:
                assert max_failures is not None
                return await self._finalize_after_failures(
                    context, emitter, state, max_failures
                )

            decision = stop.should_stop(state.iterations, chunks, complete_calls)
            logger.debug(
                "stop decision correlation_id={} stop={} reason={}",
                context.correlation_id,
                decision.stop,
                decision.reason,
            )

            if decision.stop:
                return LoopResult(
                    final_text=state.final_text,
                    tool_invocations=state.tool_invocations,
                    iterations=state.iterations,
                    stop_reason=decision.reason,
                    token_usage=state.token_usage(),
                )

    async def _execute_tool(
        self,
        tools: ToolRegistry,
        call_id: str,
        name: str,
        args_str: str,
        timeout: float | None = None,
    ) -> ToolResult:
        """Coalesce all tool-execution failure modes into ``ToolResult(is_error=True)``."""
        try:
            args = json.loads(args_str) if args_str else {}

        except json.JSONDecodeError as error:
            return ToolResult(
                tool_call_id=call_id,
                content=f"Invalid JSON arguments: {error}",
                is_error=True,
            )

        try:
            if timeout is None:
                result = await tools.execute(name, args)

            else:
                result = await asyncio.wait_for(
                    tools.execute(name, args), timeout=timeout
                )

            if result.tool_call_id != call_id:
                result = result.model_copy(update={"tool_call_id": call_id})

            return result

        except KeyError:
            return ToolResult(
                tool_call_id=call_id, content=f"Unknown tool: {name}", is_error=True
            )

        except asyncio.TimeoutError:
            return ToolResult(
                tool_call_id=call_id,
                content=f"Tool '{name}' timed out after {timeout}s",
                is_error=True,
            )

        except Exception as error:
            return ToolResult(
                tool_call_id=call_id,
                content=f"Tool '{name}' raised: {error}",
                is_error=True,
            )

    async def _finalize_after_failures(
        self,
        context: AgentContext,
        emitter: Emitter,
        state: _RunState,
        limit: int,
    ) -> LoopResult:
        """Ask the model to summarize progress after hitting the consecutive-failure limit.

        Runs one final streamed LLM call with no tools available so the model
        cannot attempt further tool calls; the result is a graceful stop, not
        a failure.
        """
        context.append_message(
            {
                "role": "user",
                "content": (
                    f"Tool execution has been stopped because {limit} consecutive "
                    "tool calls failed. Do not attempt any further tool calls. "
                    "Summarize what you tried, what failed and why, and give the "
                    "best answer you can from the information gathered so far."
                ),
            }
        )

        model_config = _build_model_config(context)
        model_config.pop("tool_choice", None)

        text_buf = ""

        async for chunk in self._llm.chat(
            messages=context.messages,
            tools=[],
            model_config=model_config,
            stream=True,
            runtime_config={
                "max_retry_limit": context.agent.max_retry_limit,
                "max_rpm": context.agent.max_rpm,
            },
        ):
            await emitter.on_chunk(chunk)

            if chunk.delta_text:
                text_buf += chunk.delta_text

            if chunk.usage:
                state.add_usage(chunk.usage)

        if text_buf:
            context.append_message({"role": "assistant", "content": text_buf})
            state.final_text = text_buf

        state.iterations += 1

        return LoopResult(
            final_text=state.final_text,
            tool_invocations=state.tool_invocations,
            iterations=state.iterations,
            stop_reason=StopReason.MAX_CONSECUTIVE_FAILURES.value,
            token_usage=state.token_usage(),
        )
