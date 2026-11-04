import re
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError
from src.shared.models.sessions import TokenUsage
from src.shared.models.system_one import (
    SystemOneAnswer,
    SystemOneConfigData,
    SystemOneQuestion,
    SystemOneResult,
)
from src.shared.system_one.base import SystemOneError
from src.shared.system_one.constants import (
    JEV_INPUT_PRICE_USD_PER_TOKEN,
    JEV_MODEL_VERSIONS,
    TYPESAFE_PROVIDER,
)

TYPESAFE_SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_TIMEOUT_SECONDS = 10.0
_JEV_VERSION = re.compile(r"jev-\d+\.\d+\.\d+")


class _Usage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class _TypeSafeResponse(BaseModel):
    model: object = None
    answers: dict[str, SystemOneAnswer]
    usage: _Usage | None = None


def _error_for_status(status_code: int) -> SystemOneError:
    if status_code in (400, 422):
        return SystemOneError(f"TypeSafe refused the request (HTTP {status_code}).")
    if status_code in (401, 403):
        return SystemOneError("TypeSafe rejected the API key.")
    if status_code == 429:
        return SystemOneError("TypeSafe rate limit reached.")
    return SystemOneError(f"TypeSafe returned HTTP {status_code}.")


class TypeSafeAdapter:
    """One POST to TypeSafe's System One endpoint per call; no retry.

    Error messages carry only the status code and our own wording, never the response body,
    headers, URL query or the key. Errors are raised outside any `except` block so that no
    httpx or pydantic exception (whose text can quote the key or the body) stays attached.
    """

    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._transport = transport

    async def evaluate(
        self,
        *,
        config: SystemOneConfigData,
        state: dict[str, Any],
        questions: dict[str, SystemOneQuestion],
    ) -> tuple[SystemOneResult, TokenUsage]:
        # A key httpx cannot put in a header raises an error whose text quotes the key.
        api_key = (config.api_key or "").strip()
        if not api_key or not (api_key.isascii() and api_key.isprintable()):
            raise SystemOneError("The config has no API key.")
        if config.model_name not in JEV_MODEL_VERSIONS:
            raise SystemOneError("The config has no supported Jev version.")

        body = {
            "model": config.model_name,
            "state": state,
            "questions": {
                name: question.model_dump(mode="json", exclude_none=True)
                for name, question in questions.items()
            },
        }
        failure: SystemOneError | None = None
        try:
            # The httpx timeout applies per phase (connect/read/write/pool), not as a total
            # deadline. The host is fixed, so this ceiling is accepted.
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=TYPESAFE_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    TYPESAFE_SYSTEM_ONE_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.TimeoutException:
            failure = SystemOneError(
                f"TypeSafe did not answer within {TYPESAFE_TIMEOUT_SECONDS:g} seconds."
            )
        except httpx.RequestError:
            failure = SystemOneError("TypeSafe is unreachable.")
        if failure:
            raise failure

        if not response.is_success:
            raise _error_for_status(response.status_code)

        try:
            parsed = _TypeSafeResponse.model_validate_json(response.content)
        except ValidationError:
            failure = SystemOneError("TypeSafe returned a malformed answer.")
        if failure:
            raise failure

        reported = parsed.model
        model_version = (
            reported
            if isinstance(reported, str) and _JEV_VERSION.fullmatch(reported)
            else config.model_name
        )
        reported_usage = parsed.usage or _Usage()
        prompt_tokens = reported_usage.input_tokens or 0
        completion_tokens = reported_usage.output_tokens or 0
        usage = TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            successful_requests=1,
            total_cost_usd=round(
                prompt_tokens * JEV_INPUT_PRICE_USD_PER_TOKEN[config.model_name], 10
            ),
        )
        result = SystemOneResult(
            answers=parsed.answers, provider=TYPESAFE_PROVIDER, model_version=model_version
        )
        return result, usage
