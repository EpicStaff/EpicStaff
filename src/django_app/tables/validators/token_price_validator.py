from rest_framework import serializers


def validate_token_prices_set_together(
    input_cost_per_token: float | None, output_cost_per_token: float | None
) -> None:
    """Require an LLM config's prompt and completion prices to be both set or both null.

    Cost uses the config's own prices only when it has both; with one of them the
    config would silently fall back to litellm's price map, so a half-set pair is
    rejected instead. The error is reported on the price that is missing.
    """
    if (input_cost_per_token is None) == (output_cost_per_token is None):
        return
    missing_field = (
        "input_cost_per_token" if input_cost_per_token is None else "output_cost_per_token"
    )
    raise serializers.ValidationError(
        {missing_field: "Set both token prices, or leave both empty."}
    )
