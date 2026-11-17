from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, Field, StrictInt, ValidationError
from src.shared.models.sessions import TokenUsage
from src.shared.models.system_one import (
    ChoiceAnswer,
    NoulAnswer,
    Probability,
    Score,
    ScoreAnswer,
    SystemOneAnswer,
    SystemOneConfigData,
    SystemOneQuestion,
    SystemOneResult,
)
from src.shared.system_one.base import SystemOneError
from src.shared.system_one.constants import (
    OPENAI_DECISIONS_MODELS,
    OPENAI_INPUT_PRICE_USD_PER_TOKEN,
    OPENAI_PROVIDER,
)

OPENAI_DECISIONS_URL = "https://api.openai.com/v1/decisions"
OPENAI_TIMEOUT_SECONDS = 10.0


class _Usage(BaseModel):
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


class _ChoiceProbability(BaseModel):
    value: str
    probability: Probability


class _ScoreProbability(BaseModel):
    value: StrictInt
    probability: Probability


class _PredicateAnswer(BaseModel):
    type: Literal["predicate"]
    name: str
    probability: Probability


class _ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    name: str
    choice: str
    confidence: Probability
    probabilities: list[_ChoiceProbability]


class _ScoreAnswer(BaseModel):
    type: Literal["score"]
    name: str
    score: Score
    confidence: Probability
    probabilities: list[_ScoreProbability]


class _RefusalAnswer(BaseModel):
    type: Literal["refusal"]
    name: str


class _DecisionsResponse(BaseModel):
    model: object = None
    answers: list[
        Annotated[
            _PredicateAnswer | _ChoiceAnswer | _ScoreAnswer | _RefusalAnswer,
            Field(discriminator="type"),
        ]
    ]
    usage: _Usage | None = None


def _convert_question(name: str, question: SystemOneQuestion) -> dict[str, Any]:
    if question.type == "noul":
        instructions = question.instructions
        for key, label in (("true", "True"), ("false", "False")):
            text = (question.criteria or {}).get(key)
            if text:
                instructions += f"\n{label} when: {text}"
        return {"type": "predicate", "name": name, "instructions": instructions}
    if question.type == "choice":
        return {
            "type": "choice",
            "name": name,
            "instructions": question.instructions,
            "choices": [
                {"value": option, **({"description": text} if text else {})}
                for option, text in question.criteria.items()
            ],
        }
    return {
        "type": "score",
        "name": name,
        "instructions": question.instructions,
        "levels": [{"label": level} for level in question.criteria],
    }


def _convert_answer(
    answer: _PredicateAnswer | _ChoiceAnswer | _ScoreAnswer,
) -> SystemOneAnswer:
    if answer.type == "predicate":
        return NoulAnswer(type="noul", noul=answer.probability)
    if answer.type == "choice":
        return ChoiceAnswer(
            type="choice",
            choice=answer.choice,
            confidence=answer.confidence,
            probabilities={item.value: item.probability for item in answer.probabilities},
        )
    return ScoreAnswer(
        type="score",
        score=answer.score,
        confidence=answer.confidence,
        probabilities={str(item.value): item.probability for item in answer.probabilities},
    )


def _error_for_status(status_code: int) -> SystemOneError:
    if status_code in (400, 422):
        return SystemOneError(f"OpenAI refused the request (HTTP {status_code}).")
    if status_code in (401, 403):
        return SystemOneError("OpenAI rejected the API key.")
    if status_code == 429:
        return SystemOneError("OpenAI rate limit reached.")
    return SystemOneError(f"OpenAI returned HTTP {status_code}.")


class OpenAIDecisionsAdapter:
    """One POST to OpenAI's Decisions endpoint per call; no retry.

    Error messages carry only the status code and our own wording, never the response body,
    headers or the key (OpenAI's 401 body quotes the start of the key). Errors are raised outside
    any `except` block so that no httpx or pydantic exception stays attached.
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
        if config.model_name not in OPENAI_DECISIONS_MODELS:
            raise SystemOneError("The config has no supported OpenAI model.")

        body = {
            "model": config.model_name,
            "input": [{"role": "user", "content": [{"type": "input_json", "data": state}]}],
            "questions": [
                _convert_question(name, question) for name, question in questions.items()
            ],
        }
        failure: SystemOneError | None = None
        try:
            # The httpx timeout applies per phase (connect/read/write/pool), not as a total
            # deadline. The host is fixed, so this ceiling is accepted.
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=OPENAI_TIMEOUT_SECONDS,
                follow_redirects=False,
            ) as client:
                response = await client.post(
                    OPENAI_DECISIONS_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {api_key}"},
                )
        except httpx.TimeoutException:
            failure = SystemOneError(
                f"OpenAI did not answer within {OPENAI_TIMEOUT_SECONDS:g} seconds."
            )
        except httpx.RequestError:
            failure = SystemOneError("OpenAI is unreachable.")
        if failure:
            raise failure

        if not response.is_success:
            raise _error_for_status(response.status_code)

        try:
            parsed = _DecisionsResponse.model_validate_json(response.content)
        except ValidationError:
            failure = SystemOneError("OpenAI returned a malformed answer.")
        if failure:
            raise failure

        # OpenAI refuses every question at once on harmful input, so one refusal fails the entry.
        if any(answer.type == "refusal" for answer in parsed.answers):
            raise SystemOneError("OpenAI declined to answer.")

        model_version = (
            parsed.model if parsed.model in OPENAI_DECISIONS_MODELS else config.model_name
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
                prompt_tokens * OPENAI_INPUT_PRICE_USD_PER_TOKEN[config.model_name], 10
            ),
        )
        result = SystemOneResult(
            answers={answer.name: _convert_answer(answer) for answer in parsed.answers},
            provider=OPENAI_PROVIDER,
            model_version=model_version,
        )
        return result, usage
