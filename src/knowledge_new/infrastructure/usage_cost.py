"""Cost of consumed tokens, from custom per-token prices or litellm's offline price map."""

from infrastructure.token_estimation import price_per_token


def embedding_cost(model: str, tokens: int) -> float | None:
    """Return the USD cost of `tokens` embedded with `model`, or None when it is unpriced."""
    prices = price_per_token(model)
    return None if prices is None else tokens * prices[0]


def llm_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    custom_input_price: float | None = None,
    custom_output_price: float | None = None,
) -> float | None:
    """Return the USD cost of an LLM's tokens, or None when it is unpriced.

    The LLM config's own prices win when both are set; otherwise litellm's price map.
    """
    if custom_input_price is not None and custom_output_price is not None:
        return input_tokens * custom_input_price + output_tokens * custom_output_price
    prices = price_per_token(model)
    if prices is None:
        return None
    return input_tokens * prices[0] + output_tokens * prices[1]


def sum_costs(*costs: float | None) -> float | None:
    """Add costs; None (an unknown price) makes the sum unknown."""
    if any(cost is None for cost in costs):
        return None
    return sum(costs)
