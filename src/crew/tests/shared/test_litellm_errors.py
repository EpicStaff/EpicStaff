"""The LLM failure -> user fact mapping the agent and crew share.

Lives in crew's suite, like the other `src.shared` tests here, because the shared
package has no test target of its own and its venv has no litellm.
"""

import inspect

import httpx
import litellm
import pytest

from src.shared.litellm_errors import LiteLLMErrorFact, describe_litellm_error


def provider_error(error_type: type[Exception], message: str = "provider said no") -> Exception:
    """Build a litellm error the way its provider adapters raise it."""
    kwargs: dict = {"message": message, "llm_provider": "openai", "model": "gpt-4o"}
    parameters = inspect.signature(error_type.__init__).parameters
    if "response" in parameters:
        kwargs["response"] = httpx.Response(500, request=httpx.Request("POST", "https://provider.test"))
    if "status_code" in parameters:
        kwargs["status_code"] = 500
    return error_type(**kwargs)


@pytest.mark.parametrize(
    ("error_type", "expected"),
    [
        (
            litellm.AuthenticationError,
            LiteLLMErrorFact("llm_auth", 'The provider rejected the API key for model "gpt-4o".'),
        ),
        (
            litellm.RateLimitError,
            LiteLLMErrorFact("llm_rate_limit", 'The provider\'s rate limit for model "gpt-4o" was reached.'),
        ),
        (
            litellm.ContextWindowExceededError,
            LiteLLMErrorFact("llm_context_window", 'The prompt is too long for model "gpt-4o".'),
        ),
        (
            litellm.NotFoundError,
            LiteLLMErrorFact("llm_model_not_found", 'The provider has no model "gpt-4o".'),
        ),
        (
            litellm.ServiceUnavailableError,
            LiteLLMErrorFact("llm_unavailable", 'The provider of model "gpt-4o" isn\'t responding.'),
        ),
        (
            litellm.APIConnectionError,
            LiteLLMErrorFact("llm_unavailable", 'The provider of model "gpt-4o" isn\'t responding.'),
        ),
        (
            litellm.ContentPolicyViolationError,
            LiteLLMErrorFact(
                "llm_content_refused",
                'The provider of model "gpt-4o" refused the request because of its content policy.',
            ),
        ),
        (
            litellm.Timeout,
            LiteLLMErrorFact("llm_timeout", 'The provider of model "gpt-4o" took too long to answer.'),
        ),
        # Parents of the classes above, and classes the table has no row for.
        (
            litellm.BadRequestError,
            LiteLLMErrorFact("llm_failed", 'The LLM request for model "gpt-4o" failed.'),
        ),
        (
            litellm.InternalServerError,
            LiteLLMErrorFact("llm_failed", 'The LLM request for model "gpt-4o" failed.'),
        ),
        (
            litellm.APIError,
            LiteLLMErrorFact("llm_failed", 'The LLM request for model "gpt-4o" failed.'),
        ),
    ],
    ids=lambda value: value.__name__ if isinstance(value, type) else None,
)
def test_each_litellm_error_maps_to_its_code_and_fact(error_type, expected):
    assert describe_litellm_error(provider_error(error_type), "gpt-4o") == expected


@pytest.mark.parametrize(
    "error",
    [RuntimeError("socket closed"), ValueError("Expecting value: line 1 column 1"), TimeoutError()],
    ids=["runtime-error", "parse-error", "timeout-error"],
)
def test_an_error_from_outside_litellm_is_not_described(error):
    assert describe_litellm_error(error, "gpt-4o") is None


def test_a_litellm_error_with_no_openai_parent_is_a_failed_request():
    error = litellm.BudgetExceededError(current_cost=2.0, max_budget=1.0)

    assert describe_litellm_error(error, "gpt-4o") == LiteLLMErrorFact(
        "llm_failed", 'The LLM request for model "gpt-4o" failed.'
    )


def test_the_providers_text_never_reaches_the_fact():
    error = provider_error(litellm.AuthenticationError, message="Incorrect API key provided: sk-abc123")

    fact = describe_litellm_error(error, "gpt-4o")

    assert "sk-abc123" not in fact.detail
