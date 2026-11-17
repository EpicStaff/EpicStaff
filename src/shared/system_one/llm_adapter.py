import json
import math
from typing import Any

from src.shared.models.sessions import TokenUsage
from src.shared.models.system_one import (
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneAnswer,
    SystemOneConfigData,
    SystemOneQuestion,
    SystemOneResult,
)
from src.shared.system_one.base import SystemOneError
from src.shared.system_one.constants import LLM_PROVIDER
from src.shared.system_one.json_llm import run_json_llm


def _build_prompt(state: dict[str, Any], questions: dict[str, SystemOneQuestion]) -> str:
    asked = {
        name: question.model_dump(mode="json", exclude_none=True)
        for name, question in questions.items()
    }
    return (
        "You are a classifier. Judge the STATE and answer every QUESTION with probabilities "
        "between 0 and 1.\n"
        "- noul: the probability that the statement is true.\n"
        "- choice: one probability per option; they sum to 1.\n"
        '- score: one probability per level, keyed by the level\'s index ("0" is the first '
        "level); they sum to 1.\n"
        f"STATE:\n{json.dumps(state, indent=2)}\n"
        f"QUESTIONS:\n{json.dumps(asked, indent=2)}\n"
        'Respond with a JSON object only: {"answers": {<question name>: <answer>}}.'
    )


def _level_keys(question: SystemOneQuestion) -> list[str]:
    if question.type == "choice":
        return list(question.criteria)
    return [str(index) for index in range(len(question.criteria))]


def _answer_schema(questions: dict[str, SystemOneQuestion]) -> dict:
    def strict(properties: dict) -> dict:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": list(properties),
            "properties": properties,
        }

    def answer(question: SystemOneQuestion) -> dict:
        if question.type == "noul":
            return strict({"noul": {"type": "number"}})
        keys = _level_keys(question)
        return strict({"probabilities": strict({key: {"type": "number"} for key in keys})})

    return strict({"answers": strict({name: answer(q) for name, q in questions.items()})})


def _number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError("not a finite number")
    return float(value)


def _normalised_probabilities(raw: Any, keys: list[str]) -> dict[str, float]:
    if not isinstance(raw, dict) or not isinstance(raw.get("probabilities"), dict):
        raise TypeError("no probabilities")
    reported = raw["probabilities"]
    clamped = {key: max(_number(reported.get(key, 0)), 0.0) for key in keys}
    total = sum(clamped.values())
    if not math.isfinite(total) or total <= 0:
        raise ValueError("probabilities do not sum to a positive number")
    return {key: value / total for key, value in clamped.items()}


def _derive_answer(question: SystemOneQuestion, raw: Any) -> SystemOneAnswer:
    if question.type == "noul":
        if not isinstance(raw, dict):
            raise TypeError("no noul")
        return NoulAnswer(type="noul", noul=min(max(_number(raw.get("noul")), 0.0), 1.0))

    probabilities = _normalised_probabilities(raw, _level_keys(question))
    top_key = max(probabilities, key=probabilities.__getitem__)
    confidence = probabilities[top_key]
    if question.type == "choice":
        return ChoiceAnswer(
            type="choice", choice=top_key, confidence=confidence, probabilities=probabilities
        )
    score = sum(int(key) * value for key, value in probabilities.items())
    return ScoreAnswer(
        type="score", score=score, confidence=confidence, probabilities=probabilities
    )


class LlmSystemOneAdapter:
    """Answers the questions with the config's LLM and derives TypeSafe-shaped answers.

    The LLM reports probabilities itself, so `confidence` is self-reported, not calibrated.
    Error messages never carry the LLM output or provider text.
    """

    async def evaluate(
        self,
        *,
        config: SystemOneConfigData,
        state: dict[str, Any],
        questions: dict[str, SystemOneQuestion],
    ) -> tuple[SystemOneResult, TokenUsage]:
        if config.llm_data is None:
            raise SystemOneError("This System One config has no LLM config.")

        prompt = _build_prompt(state, questions)
        try:
            payload, usage = await run_json_llm(
                prompt=prompt,
                llm=config.llm_data,
                output_schema=_answer_schema(questions),
            )
        except Exception as error:
            raise SystemOneError("The LLM call failed.") from error

        reported = payload.get("answers") if isinstance(payload, dict) else None
        if not isinstance(reported, dict):
            reported = {}
        answers: dict[str, SystemOneAnswer] = {}
        for name, question in questions.items():
            try:
                answers[name] = _derive_answer(question, reported.get(name))
            except (TypeError, ValueError, OverflowError):
                raise SystemOneError(f"The LLM returned no valid answer for '{name}'.") from None

        result = SystemOneResult(
            answers=answers, provider=LLM_PROVIDER, model_version=config.llm_data.config.model
        )
        return result, usage
