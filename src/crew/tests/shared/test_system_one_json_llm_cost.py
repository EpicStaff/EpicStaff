"""
Tests for the cost run_json_llm reports:
the LLM config's own token prices when both are set, litellm's price map otherwise.

Only litellm.acompletion is mocked; it returns a real litellm ModelResponse so the
cost is computed by litellm itself.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import litellm
import pytest
from litellm.types.utils import ModelResponse, Usage

from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.system_one.json_llm import run_json_llm

UNPRICED_MODEL = "epicstaff-test-gateway-model-without-price"
PROMPT = "Classify the following: hello world"


def make_response(model: str, usage: Usage) -> ModelResponse:
    return ModelResponse(
        model=model,
        choices=[{"message": {"role": "assistant", "content": '{"label": "positive"}'}}],
        usage=usage,
    )


@pytest.fixture
def mock_completion():
    with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
        yield completion


@pytest.mark.asyncio
async def test_cost_uses_the_config_prices_when_both_are_set(mock_completion):
    mock_completion.return_value = make_response(
        f"openai/{UNPRICED_MODEL}",
        Usage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
    )
    llm = LLMData(
        provider="openai",
        config=LLMConfigData(
            model=UNPRICED_MODEL, input_cost_per_token=0.001, output_cost_per_token=0.002
        ),
    )

    _result, usage = await run_json_llm(prompt=PROMPT, llm=llm)

    assert usage.total_cost_usd == pytest.approx(100 * 0.001 + 20 * 0.002)


@pytest.mark.asyncio
async def test_cached_prompt_tokens_are_billed_once_at_the_input_price(mock_completion):
    # litellm's Anthropic usage: prompt_tokens already include the 40 cache reads.
    mock_completion.return_value = make_response(
        "anthropic/claude-3-5-sonnet-20240620",
        Usage(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=120,
            cache_read_input_tokens=40,
        ),
    )
    llm = LLMData(
        provider="anthropic",
        config=LLMConfigData(
            model="claude-3-5-sonnet-20240620",
            input_cost_per_token=0.001,
            output_cost_per_token=0.002,
        ),
    )

    _result, usage = await run_json_llm(prompt=PROMPT, llm=llm)

    assert usage.cached_prompt_tokens == 40
    assert usage.total_cost_usd == pytest.approx(100 * 0.001 + 20 * 0.002)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "prices",
    [{}, {"input_cost_per_token": 0.001}, {"output_cost_per_token": 0.002}],
    ids=["no-prices", "input-only", "output-only"],
)
async def test_cost_falls_back_to_the_price_map_without_both_prices(mock_completion, prices):
    response = make_response(
        "gpt-4o", Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    )
    mock_completion.return_value = response
    llm = LLMData(provider="openai", config=LLMConfigData(model="gpt-4o", **prices))

    _result, usage = await run_json_llm(prompt=PROMPT, llm=llm)

    expected = litellm.completion_cost(completion_response=response)
    assert expected > 0
    assert usage.total_cost_usd == pytest.approx(expected)


@pytest.mark.asyncio
async def test_unpriced_model_without_config_prices_costs_zero(mock_completion):
    mock_completion.return_value = make_response(
        f"openai/{UNPRICED_MODEL}",
        Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    llm = LLMData(provider="openai", config=LLMConfigData(model=UNPRICED_MODEL))

    _result, usage = await run_json_llm(prompt=PROMPT, llm=llm)

    assert usage.total_cost_usd == 0.0


@pytest.mark.asyncio
async def test_token_prices_are_not_sent_to_acompletion(mock_completion):
    mock_completion.return_value = make_response(
        f"openai/{UNPRICED_MODEL}",
        Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )
    llm = LLMData(
        provider="openai",
        config=LLMConfigData(
            model=UNPRICED_MODEL, input_cost_per_token=0.001, output_cost_per_token=0.002
        ),
    )

    await run_json_llm(prompt=PROMPT, llm=llm)

    call_kwargs = mock_completion.call_args.kwargs
    assert "input_cost_per_token" not in call_kwargs
    assert "output_cost_per_token" not in call_kwargs
