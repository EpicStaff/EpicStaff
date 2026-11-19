"""The single rule for turning a failed litellm call into a fact the user can read.

Used by the agent service (Agent and Task nodes) and by crew (Classification Table
prompts), so the same failure reads the same in both. The provider's own message can
quote the API key, the endpoint or the prompt: it is never part of the fact, and the
caller logs it. Imports litellm, so only import it from a service that has litellm.
"""

from dataclasses import dataclass

import litellm

__all__ = ["LiteLLMErrorFact", "describe_litellm_error"]


@dataclass(frozen=True)
class LiteLLMErrorFact:
    """What went wrong with an LLM call: a stable machine `code` and a user-safe `detail`."""

    code: str
    detail: str


# Checked in this order, so a subclass must come before its parent:
# ContextWindowExceededError and ContentPolicyViolationError subclass BadRequestError.
# An out-of-credit answer arrives as RateLimitError; litellm has no class of its own for it.
_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("ContextWindowExceededError",),
        "llm_context_window",
        'The prompt is too long for model "{model}".',
    ),
    (
        ("ContentPolicyViolationError",),
        "llm_content_refused",
        'The provider of model "{model}" refused the request because of its content policy.',
    ),
    (
        ("AuthenticationError",),
        "llm_auth",
        'The provider rejected the API key for model "{model}".',
    ),
    (
        ("RateLimitError",),
        "llm_rate_limit",
        'The provider\'s rate limit for model "{model}" was reached.',
    ),
    (("NotFoundError",), "llm_model_not_found", 'The provider has no model "{model}".'),
    (("Timeout",), "llm_timeout", 'The provider of model "{model}" took too long to answer.'),
    (
        ("ServiceUnavailableError", "APIConnectionError"),
        "llm_unavailable",
        'The provider of model "{model}" isn\'t responding.',
    ),
)
_FAILED_CODE = "llm_failed"
_FAILED_DETAIL = 'The LLM request for model "{model}" failed.'


def _resolve(names: tuple[str, ...]) -> tuple[type[BaseException], ...]:
    # A class missing from the installed litellm is skipped, so its errors read as the
    # generic failure instead of breaking the import.
    return tuple(cls for name in names if (cls := getattr(litellm, name, None)) is not None)


_RESOLVED_RULES = tuple((_resolve(names), code, detail) for names, code, detail in _RULES)


def _is_llm_error(error: BaseException) -> bool:
    # litellm's errors subclass openai's, except a few of its own (budget, guardrail).
    return any(
        cls.__module__.partition(".")[0] in ("litellm", "openai") for cls in type(error).__mro__
    )


def describe_litellm_error(error: BaseException, model_name: str) -> LiteLLMErrorFact | None:
    """Return the code and user-safe fact for a failed LLM call.

    Args:
        error: The exception the litellm call raised. A litellm or openai error the table
            has no row for is the generic `llm_failed`.
        model_name: The model as the user configured it; the fact names it.

    Returns:
        None when `error` isn't a litellm or openai error (a bug, a parse failure, a
        timeout of our own): it says nothing about the LLM, so the caller uses its own fact.
    """
    if not _is_llm_error(error):
        return None
    for classes, code, detail in _RESOLVED_RULES:
        if classes and isinstance(error, classes):
            return LiteLLMErrorFact(code, detail.format(model=model_name))
    return LiteLLMErrorFact(_FAILED_CODE, _FAILED_DETAIL.format(model=model_name))
