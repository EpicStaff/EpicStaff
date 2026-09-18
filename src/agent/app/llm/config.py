"""Process-wide litellm configuration."""

from __future__ import annotations

import litellm


def configure_litellm(drop_unsupported_params: bool) -> None:
    """When True, litellm drops provider-unsupported params (e.g.
    presence_penalty/frequency_penalty on Anthropic) instead of raising
    UnsupportedParamsError."""
    litellm.drop_params = drop_unsupported_params
