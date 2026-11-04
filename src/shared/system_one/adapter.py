from typing import Any

from src.shared.models.sessions import TokenUsage
from src.shared.models.system_one import SystemOneConfigData, SystemOneQuestion, SystemOneResult
from src.shared.system_one.base import SystemOneAdapter, SystemOneError
from src.shared.system_one.constants import LLM_PROVIDER, TYPESAFE_PROVIDER
from src.shared.system_one.llm_adapter import LlmSystemOneAdapter
from src.shared.system_one.typesafe_adapter import TypeSafeAdapter

SYSTEM_ONE_ADAPTERS: dict[str, SystemOneAdapter] = {
    TYPESAFE_PROVIDER: TypeSafeAdapter(),
    LLM_PROVIDER: LlmSystemOneAdapter(),
}


def _check_answers(
    result: SystemOneResult, questions: dict[str, SystemOneQuestion]
) -> SystemOneResult:
    for name, question in questions.items():
        answer = result.answers.get(name)
        if answer is None:
            raise SystemOneError(f"No answer for question '{name}'.")
        if answer.type != question.type:
            raise SystemOneError(
                f"Answer for question '{name}' has type '{answer.type}', "
                f"expected '{question.type}'."
            )
        if answer.type == "choice" and answer.choice not in question.criteria:
            raise SystemOneError(
                f"Answer for question '{name}' chose an option that was not asked."
            )
    asked = {name: result.answers[name] for name in questions}
    return result.model_copy(update={"answers": asked})


async def evaluate(
    config: SystemOneConfigData,
    state: dict[str, Any],
    questions: dict[str, SystemOneQuestion],
) -> tuple[SystemOneResult, TokenUsage]:
    adapter = SYSTEM_ONE_ADAPTERS.get(config.provider)
    if adapter is None:
        raise SystemOneError(f"No System One adapter for provider '{config.provider}'.")
    try:
        result, usage = await adapter.evaluate(config=config, state=state, questions=questions)
    except SystemOneError:
        raise
    except Exception as error:
        raise SystemOneError(f"System One provider '{config.provider}' failed.") from error
    return _check_answers(result, questions), usage
