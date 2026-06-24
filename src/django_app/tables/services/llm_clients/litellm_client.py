from __future__ import annotations

import json
from collections import defaultdict
from typing import AsyncIterator

import litellm

from utils.logger import logger

from .base import (
    BaseLLMClient,
    DoneEvent,
    StreamEvent,
    TokenEvent,
    ToolCallEvent,
    ToolSpec,
    UnsupportedLLMProviderError,
)


class LiteLLMClient(BaseLLMClient):
    """Unified streaming + tool-calling client for all LiteLLM-supported providers.

    Replaces the former per-provider OpenAILLMClient and AnthropicLLMClient wrappers.
    Both of those classes already called litellm.acompletion internally; this class
    consolidates them into one.  Adding a new provider (Gemini, Mistral, Cohere,
    Bedrock, etc.) is now a config-row change — zero FA code change required.

    Model-string conventions (per LiteLLM docs):
      - OpenAI:           "<model-name>"          e.g. "gpt-4o"
      - Azure:            "azure/<deployment>"    e.g. "azure/gpt-4o-deployment"
      - Anthropic:        "anthropic/<model>"     e.g. "anthropic/claude-3-5-sonnet-20241022"
      - All others:       "<provider>/<model>"    e.g. "gemini/gemini-1.5-pro"

    Known limitation (unchanged from prior clients): LiteLLM's stream cancellation does
    not close the upstream HTTP connection to the LLM provider.  Our cancel-stream
    feature (Redis flag + DoneEvent(interrupted=True)) remains correct from the
    application's perspective, but the provider keeps generating tokens in the
    background.  This pre-existed Phase 5 — both prior clients exhibited the same
    behavior because they also used LiteLLM internally.  Tracked separately.
    """

    def __init__(self, llm_config, output_schema: dict | None = None) -> None:
        super().__init__(output_schema=output_schema)
        self._llm_config = llm_config
        # Validate and cache the model string eagerly so callers receive
        # UnsupportedLLMProviderError at construction time (fail-fast), not
        # lazily during the first stream_completion call.
        self._model = self._model_string()

    def _model_string(self) -> str:
        """Build the LiteLLM model string from llm_config.model.

        Raises UnsupportedLLMProviderError when the provider or model name is
        missing so callers receive a clear domain exception instead of a
        cryptic AttributeError or litellm error.
        """
        model = self._llm_config.model
        if not model:
            raise UnsupportedLLMProviderError("(no model configured)")

        model_name = (model.name or "").strip()
        if not model_name:
            raise UnsupportedLLMProviderError("(empty model name)")

        provider_name = (
            (model.llm_provider.name or "").lower().strip() if model.llm_provider else ""
        )

        if not provider_name or provider_name == "openai":
            # Plain model name for OpenAI; litellm defaults to OpenAI for bare names.
            return model_name

        if provider_name in ("azure", "azure_openai"):
            # Azure uses the deployment name, falling back to model name if not set.
            deployment = (getattr(model, "deployment_id", None) or model_name).strip()
            return f"azure/{deployment}"

        # All other providers: "<provider>/<model>" — litellm understands this format
        # for Anthropic, Gemini, Mistral, Cohere, Bedrock, Together, etc.
        return f"{provider_name}/{model_name}"

    def _build_tools(self, tools: list[ToolSpec]) -> list[dict] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in tools
        ]

    def _build_kwargs(self, messages: list[dict], tools: list[ToolSpec]) -> dict:
        cfg = self._llm_config
        model = cfg.model

        kwargs: dict = {
            "model": self._model,
            "messages": messages,
            "stream": True,
        }

        if cfg.api_key:
            kwargs["api_key"] = cfg.api_key
        if model and model.base_url:
            kwargs["base_url"] = model.base_url
        if model and getattr(model, "api_version", None):
            kwargs["api_version"] = model.api_version
        if cfg.temperature is not None:
            kwargs["temperature"] = cfg.temperature
        if cfg.max_tokens is not None:
            kwargs["max_tokens"] = cfg.max_tokens
        if cfg.top_p is not None:
            kwargs["top_p"] = cfg.top_p
        if getattr(cfg, "presence_penalty", None) is not None:
            kwargs["presence_penalty"] = cfg.presence_penalty
        if getattr(cfg, "frequency_penalty", None) is not None:
            kwargs["frequency_penalty"] = cfg.frequency_penalty
        if getattr(cfg, "seed", None) is not None:
            kwargs["seed"] = cfg.seed
        if cfg.timeout is not None:
            kwargs["timeout"] = cfg.timeout
        # Caller-supplied output_schema takes precedence over the config-level
        # response_format field so the structured-output feature can override
        # without mutating the persisted LLMConfig row.
        if self._output_schema:
            kwargs["response_format"] = {
                "type": "json_schema",
                "json_schema": self._output_schema,
            }
        elif getattr(cfg, "response_format", None):
            kwargs["response_format"] = cfg.response_format
        if getattr(cfg, "extra_headers", None):
            kwargs["extra_headers"] = cfg.extra_headers

        tool_list = self._build_tools(tools)
        if tool_list:
            kwargs["tools"] = tool_list

        return kwargs

    async def stream_completion(
        self,
        messages: list[dict],
        tools: list[ToolSpec],
    ) -> AsyncIterator[StreamEvent]:
        kwargs = self._build_kwargs(messages, tools)
        logger.debug("LiteLLMClient calling model {}", kwargs.get("model"))

        # Accumulate tool-call chunks keyed by tool_call.index.
        # Each accumulator entry holds: {"id": str, "name": str, "args": str}
        tool_calls_accumulator: dict[int, dict] = defaultdict(
            lambda: {"id": "", "name": "", "args": ""}
        )

        # Track whether the model emitted any `delta.reasoning_content`
        # during this turn. Reasoning models (gpt-oss, o1, claude-thinking,
        # DeepSeek-R1) populate this; non-reasoning models leave it absent.
        reasoning_observed = False

        response = await litellm.acompletion(**kwargs)

        async for chunk in response:
            delta = chunk.choices[0].delta if chunk.choices else None
            if delta is None:
                continue

            # Silently consume reasoning tokens — never forwarded as TokenEvent
            # (FE shows "status only" per design). Just record the fact;
            # surfaced via DoneEvent at end-of-stream for the service gate.
            if getattr(delta, "reasoning_content", None):
                reasoning_observed = True

            # Text token
            if delta.content:
                yield TokenEvent(content=delta.content)

            # Tool call chunks — accumulate incrementally by index
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    acc = tool_calls_accumulator[tc.index]
                    if tc.id:
                        acc["id"] = tc.id
                    if tc.function and tc.function.name:
                        acc["name"] = tc.function.name
                    if tc.function and tc.function.arguments:
                        acc["args"] += tc.function.arguments

            finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
            # Anthropic surfaces "tool_use" and "end_turn"; OpenAI uses "tool_calls"
            # and "stop".  LiteLLM normalises most of this, but we handle all known
            # variants defensively to stay robust across litellm version changes.
            if finish_reason in ("tool_calls", "stop", "tool_use", "end_turn"):
                break

        # Emit accumulated tool calls (if any) once the stream is done.
        for acc in tool_calls_accumulator.values():
            if acc["name"]:
                try:
                    args = json.loads(acc["args"]) if acc["args"] else {}
                except json.JSONDecodeError:
                    args = {"_raw": acc["args"]}
                yield ToolCallEvent(id=acc["id"], name=acc["name"], args=args)

        yield DoneEvent(reasoning_observed=reasoning_observed)
