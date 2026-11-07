"""Classify a failed LLM call into an ``LLMErrorKind`` crew can explain to the user.

Used by the agent service, for an agent's LLM calls, and by crew, for a Classification
Decision Table's prompts. Imports litellm, so only import it from a service that has litellm.
"""

from __future__ import annotations

from litellm.exceptions import (
    LITELLM_EXCEPTION_TYPES,
    APIConnectionError,
    AuthenticationError,
    BadGatewayError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    InternalServerError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    Timeout,
)

from .models.agent_service import LLMErrorKind

# The classes litellm maps every provider error to; litellm checks the same list to
# tell an error it has already mapped.
_LITELLM_ERRORS: tuple[type[BaseException], ...] = tuple(LITELLM_EXCEPTION_TYPES)

# The first matching class wins. ContextWindowExceededError and
# ContentPolicyViolationError are BadRequestErrors, which as a whole stay UNKNOWN: a 400
# alone says nothing the user can act on.
_KIND_BY_EXCEPTION: tuple[tuple[type[BaseException], LLMErrorKind], ...] = (
    (ContextWindowExceededError, LLMErrorKind.CONTEXT_TOO_LONG),
    (ContentPolicyViolationError, LLMErrorKind.CONTENT_REFUSED),
    (AuthenticationError, LLMErrorKind.AUTHENTICATION),
    (PermissionDeniedError, LLMErrorKind.AUTHENTICATION),
    (NotFoundError, LLMErrorKind.MODEL_NOT_FOUND),
    (Timeout, LLMErrorKind.PROVIDER_TIMEOUT),
    (ServiceUnavailableError, LLMErrorKind.PROVIDER_UNAVAILABLE),
    (InternalServerError, LLMErrorKind.PROVIDER_UNAVAILABLE),
    (BadGatewayError, LLMErrorKind.PROVIDER_UNAVAILABLE),
    (APIConnectionError, LLMErrorKind.PROVIDER_UNAVAILABLE),
)

# How an OpenAI-compatible provider says a 429 means the account is out of credit rather
# than over its rate limit. litellm keeps only the message of OpenAI's error body, so the
# "insufficient_quota" code is usually gone by the time the error reaches us; OpenAI's
# message text is what stays. Other providers' quota errors read like rate limits, so
# they stay RATE_LIMIT.
_QUOTA_EXHAUSTED_MARKERS = ("insufficient_quota", "exceeded your current quota")


def is_quota_exhausted(error: BaseException) -> bool:
    """Return whether ``error`` is a 429 saying the provider account has run out of credit."""
    if not isinstance(error, RateLimitError):
        return False
    text = str(error).lower()
    return any(marker in text for marker in _QUOTA_EXHAUSTED_MARKERS)


def classify_llm_error(error: BaseException) -> LLMErrorKind | None:
    """Return what kind of LLM failure ``error`` is.

    The exception class decides it; the message is read only to tell a quota 429 from a
    rate-limit one.

    Returns:
        ``UNKNOWN`` for a litellm error crew can't name, and ``None`` for an exception
        that isn't a litellm error at all (a Redis or emitter failure, a bug): that is
        not an LLM failure, and must not be shown to the user as one.
    """
    if not isinstance(error, _LITELLM_ERRORS):
        return None

    if isinstance(error, RateLimitError):
        if is_quota_exhausted(error):
            return LLMErrorKind.QUOTA_EXCEEDED
        return LLMErrorKind.RATE_LIMIT

    for exception_class, kind in _KIND_BY_EXCEPTION:
        if isinstance(error, exception_class):
            return kind

    return LLMErrorKind.UNKNOWN
