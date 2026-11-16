import pytest
from src.shared.models.sessions import TokenUsage
from src.shared.models.system_one import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    SystemOneConfigData,
    SystemOneResult,
)
from src.shared.system_one.adapter import SYSTEM_ONE_ADAPTERS, SystemOneError, evaluate

CONFIG = SystemOneConfigData(id=1, provider="fake")
USAGE = TokenUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7)
QUESTIONS = {
    "is_engineering": NoulQuestion(type="noul", instructions="Engineering company?"),
    "dept": ChoiceQuestion(
        type="choice",
        instructions="Department",
        criteria={"eng": "Engineering", "ops": "Operations"},
    ),
}
NOUL_ANSWER = NoulAnswer(type="noul", noul=0.9)
CHOICE_ANSWER = ChoiceAnswer(
    type="choice", choice="eng", confidence=0.8, probabilities={"eng": 0.8, "ops": 0.2}
)


def make_result(**answers):
    return SystemOneResult(answers=answers, provider="fake", model_version="v1")


class FakeAdapter:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def evaluate(self, *, config, state, questions):
        self.calls.append({"config": config, "state": state, "questions": questions})
        if self.error:
            raise self.error
        return self.result, USAGE


@pytest.fixture
def register(monkeypatch):
    def _register(adapter):
        monkeypatch.setitem(SYSTEM_ONE_ADAPTERS, "fake", adapter)
        return adapter

    return _register


@pytest.mark.asyncio
async def test_evaluate_calls_the_adapter_for_the_config_provider(register):
    result = make_result(is_engineering=NOUL_ANSWER, dept=CHOICE_ANSWER)
    adapter = register(FakeAdapter(result=result))
    state = {"variables": {"company": "Acme"}}

    returned, usage = await evaluate(CONFIG, state, QUESTIONS)

    assert adapter.calls == [{"config": CONFIG, "state": state, "questions": QUESTIONS}]
    assert returned == result
    assert usage == USAGE


@pytest.mark.asyncio
async def test_unknown_provider_is_a_system_one_error():
    with pytest.raises(SystemOneError) as error:
        await evaluate(SystemOneConfigData(id=1, provider="nope"), {}, QUESTIONS)

    assert str(error.value) == "No System One adapter for provider 'nope'."


@pytest.mark.asyncio
async def test_missing_answer_is_named(register):
    register(FakeAdapter(result=make_result(is_engineering=NOUL_ANSWER)))

    with pytest.raises(SystemOneError) as error:
        await evaluate(CONFIG, {}, QUESTIONS)

    assert str(error.value) == "No answer for question 'dept'."


@pytest.mark.asyncio
async def test_wrong_answer_type_is_refused(register):
    wrong = ScoreAnswer(type="score", score=1, confidence=0.5, probabilities={"0": 0.5, "1": 0.5})
    register(FakeAdapter(result=make_result(is_engineering=wrong, dept=CHOICE_ANSWER)))

    with pytest.raises(SystemOneError) as error:
        await evaluate(CONFIG, {}, QUESTIONS)

    assert (
        str(error.value)
        == "Answer for question 'is_engineering' has type 'score', expected 'noul'."
    )


@pytest.mark.asyncio
async def test_choice_outside_the_options_is_refused(register):
    bad = CHOICE_ANSWER.model_copy(update={"choice": "legal"})
    register(FakeAdapter(result=make_result(is_engineering=NOUL_ANSWER, dept=bad)))

    with pytest.raises(SystemOneError) as error:
        await evaluate(CONFIG, {}, QUESTIONS)

    assert str(error.value) == "Answer for question 'dept' chose an option that was not asked."


@pytest.mark.asyncio
async def test_unasked_answers_are_dropped(register):
    register(
        FakeAdapter(
            result=make_result(is_engineering=NOUL_ANSWER, dept=CHOICE_ANSWER, extra=NOUL_ANSWER)
        )
    )

    returned, usage = await evaluate(CONFIG, {}, QUESTIONS)

    assert list(returned.answers) == ["is_engineering", "dept"]
    assert (returned.provider, returned.model_version) == ("fake", "v1")
    assert usage == USAGE


@pytest.mark.asyncio
async def test_adapter_system_one_error_passes_through(register):
    original = SystemOneError("Provider said no.")
    register(FakeAdapter(error=original))

    with pytest.raises(SystemOneError) as error:
        await evaluate(CONFIG, {}, QUESTIONS)

    assert error.value is original


@pytest.mark.asyncio
async def test_unexpected_adapter_error_is_wrapped_without_its_text(register):
    original = RuntimeError("401 key=ts-secret body=<html>")
    register(FakeAdapter(error=original))

    with pytest.raises(SystemOneError) as error:
        await evaluate(CONFIG, {}, QUESTIONS)

    assert str(error.value) == "System One provider 'fake' failed."
    assert "ts-secret" not in str(error.value)
    assert "401" not in str(error.value)
    assert error.value.__cause__ is original
