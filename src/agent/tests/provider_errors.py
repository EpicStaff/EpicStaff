"""Provider errors built the way a real call produces them, for tests that read their text.

A hand-written message drifts from what litellm actually raises: litellm 1.100.5 keeps only
the message of OpenAI's error body, so a quota 429 arrives without its
``insufficient_quota`` code. These helpers make a real ``litellm.acompletion`` call whose
OpenAI client answers from a mock HTTP transport, so the error goes through the same openai
SDK and litellm exception mapping a live provider's answer does.
"""

from __future__ import annotations

import httpx
import litellm
import openai

# OpenAI's response body for a 429 from an account that is out of credit.
OPENAI_QUOTA_BODY = {
    "error": {
        "message": (
            "You exceeded your current quota, please check your plan and billing details. "
            "For more information on this error, read the docs: "
            "https://platform.openai.com/docs/guides/error-codes/api-errors."
        ),
        "type": "insufficient_quota",
        "param": None,
        "code": "insufficient_quota",
    }
}

# OpenAI's response body for a 429 from an account over its rate limit.
OPENAI_RATE_LIMIT_BODY = {
    "error": {
        "message": (
            "Rate limit reached for gpt-4o in organization org-abc on requests per min (RPM): "
            "Limit 500, Used 500, Requested 1. Please try again in 120ms."
        ),
        "type": "requests",
        "param": None,
        "code": "rate_limit_exceeded",
    }
}


async def litellm_error_from_openai_response(status_code: int, body: dict) -> Exception:
    """Return the litellm exception an OpenAI chat completion answering ``body`` raises."""

    answered: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        answered.append(request)
        return httpx.Response(status_code, json=body)

    client = openai.AsyncOpenAI(
        api_key="sk-test",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(answer)),
    )
    try:
        await litellm.acompletion(
            model="gpt-4o",
            messages=[{"role": "user", "content": "Hi"}],
            api_key="sk-test",
            max_retries=0,
            client=client,
        )
    except Exception as error:
        # Proves litellm used the given client rather than calling the real API.
        assert [request.url.path for request in answered] == ["/v1/chat/completions"]
        return error
    finally:
        await client.close()
    raise AssertionError(f"the mocked {status_code} response did not raise")
