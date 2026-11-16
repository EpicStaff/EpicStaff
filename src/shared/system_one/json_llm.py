import json
import re
from typing import Any

import litellm
from litellm.types.utils import CostPerToken
from loguru import logger
from src.shared.litellm_model_names import litellm_call_model, litellm_routed_provider
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.models.sessions import TokenUsage

# litellm reports json_schema support for these providers, but their APIs reject it
# ("This response_format type is unavailable now") and only accept json_object.
JSON_OBJECT_ONLY_PROVIDERS = {"deepseek"}


def custom_cost_per_token(llm_config: LLMConfigData) -> CostPerToken | None:
    """Return the config's own token prices, or None when it does not set both."""
    if llm_config.input_cost_per_token is None or llm_config.output_cost_per_token is None:
        return None
    return CostPerToken(
        input_cost_per_token=llm_config.input_cost_per_token,
        output_cost_per_token=llm_config.output_cost_per_token,
    )


def extract_first_json_object(text: str) -> Any:
    """Extract the first JSON object from a text string."""
    cleaned = text.replace("```", "")
    cleaned = re.sub(r"\bjson\b", "", cleaned, flags=re.IGNORECASE)

    start = cleaned.find("{")
    if start == -1:
        return text

    depth = 0
    for i in range(start, len(cleaned)):
        ch = cleaned[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = cleaned[start : i + 1]
                try:
                    return json.loads(candidate)
                except Exception:
                    return text
    return text


async def run_json_llm(
    prompt: str, llm: LLMData, output_schema: dict | str | None = None
) -> tuple[Any, TokenUsage]:
    """Call LLM via litellm and parse JSON response."""
    llm_config = llm.config
    litellm.drop_params = True

    response_format = None
    schema = output_schema
    if isinstance(schema, str) and schema.strip():
        try:
            schema = json.loads(schema)
        except (ValueError, TypeError):
            logger.warning(
                "Prompt output_schema is not valid JSON; sending request without a response_format."
            )
            schema = None
    messages = [{"role": "user", "content": prompt}]
    if isinstance(schema, dict) and schema:
        if llm.provider.lower().strip() in JSON_OBJECT_ONLY_PROVIDERS:
            response_format = {"type": "json_object"}
            # json_object mode carries no schema and requires the word "json" in the
            # prompt; the user-written prompt guarantees neither, so state both here.
            messages.insert(
                0,
                {
                    "role": "system",
                    "content": (
                        "Respond with a JSON object that matches this JSON schema: "
                        f"{json.dumps(schema)}"
                    ),
                },
            )
        else:
            response_format = {
                "type": "json_schema",
                "json_schema": {
                    "name": "cdt_prompt_output",
                    "schema": schema,
                    "strict": True,
                },
            }

    model = litellm_call_model(llm.provider, llm_config.model, llm_config.deployment_id)
    logger.debug("Calling litellm model={} (row provider {})", model, llm.provider)
    params = {
        "model": model,
        **llm_config.to_litellm_kwargs(provider=litellm_routed_provider(model)),
        "response_format": response_format,
        "base_url": llm_config.base_url,
        "api_version": llm_config.api_version,
        "api_key": llm_config.api_key,
        "extra_headers": llm_config.extra_headers,
        "stream": False,
    }
    resp = await litellm.acompletion(**{**params, "messages": messages})

    custom_prices = custom_cost_per_token(llm_config)
    try:
        if custom_prices is not None:
            # Not completion_cost: with a custom price it bills Anthropic cache reads
            # twice, since litellm's prompt_tokens already include them. Cached
            # prompt tokens are billed at the input price.
            prompt_cost, completion_cost = litellm.cost_per_token(
                model=model,
                prompt_tokens=resp.usage.prompt_tokens,
                completion_tokens=resp.usage.completion_tokens,
                custom_cost_per_token=custom_prices,
            )
            cost = prompt_cost + completion_cost
        else:
            cost = litellm.completion_cost(completion_response=resp)
    except Exception:
        cost = 0.0  # litellm raises for models without a pricing entry — don't crash CDT

    cached_tokens = 0
    details = getattr(resp.usage, "prompt_tokens_details", None) if hasattr(resp, "usage") else None
    if details is not None:
        cached_tokens = getattr(details, "cached_tokens", 0) or 0

    usage = TokenUsage(
        total_tokens=getattr(resp.usage, "total_tokens", 0) if hasattr(resp, "usage") else 0,
        prompt_tokens=getattr(resp.usage, "prompt_tokens", 0) if hasattr(resp, "usage") else 0,
        completion_tokens=getattr(resp.usage, "completion_tokens", 0)
        if hasattr(resp, "usage")
        else 0,
        successful_requests=1,
        cached_prompt_tokens=cached_tokens,
        total_cost_usd=cost,
    )

    content = resp.choices[0].message.content
    if not isinstance(content, str):
        return content, usage
    return extract_first_json_object(content), usage
