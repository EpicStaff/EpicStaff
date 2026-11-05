import json
from unittest.mock import AsyncMock, patch

import litellm
import pytest
from litellm.types.utils import ModelResponse, Usage
from src.shared.models.ai_providers import LLMConfigData, LLMData
from src.shared.models.system_one import SYSTEM_ONE_QUESTIONS_ADAPTER, SystemOneConfigData
from src.shared.system_one.adapter import SYSTEM_ONE_ADAPTERS
from src.shared.system_one.base import SystemOneError
from src.shared.system_one.llm_adapter import LlmSystemOneAdapter

QUESTIONS = SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(
    {
        "is_engineering": {"type": "noul", "instructions": "Is this an engineering company?"},
        "department": {
            "type": "choice",
            "instructions": "Department",
            "criteria": {"engineering": "Eng", "sales": "Sales"},
        },
        "seniority": {
            "type": "score",
            "instructions": "Seniority",
            "criteria": ["junior", "mid", "senior"],
        },
    }
)
STATE = {"company": "Acme Robotics", "note": "café"}
LLM = LLMData(provider="openai", config=LLMConfigData(model="gpt-4o-mini"))
LLM_ANSWER = {
    "answers": {
        "is_engineering": {"noul": 0.92},
        "department": {"probabilities": {"engineering": 3, "sales": 1}},
        "seniority": {"probabilities": {"0": 0.1, "1": 0.4, "2": 0.5}},
    }
}


def response_with(content: str) -> ModelResponse:
    return ModelResponse(
        model="gpt-4o-mini",
        choices=[{"message": {"role": "assistant", "content": content}}],
        usage=Usage(prompt_tokens=50, completion_tokens=20, total_tokens=70),
    )


def with_answers(**overrides) -> str:
    return json.dumps({"answers": {**LLM_ANSWER["answers"], **overrides}})


@pytest.fixture
def mock_completion():
    with patch("litellm.acompletion", new_callable=AsyncMock) as completion:
        yield completion


async def evaluate_with(content: str, mock_completion):
    mock_completion.return_value = response_with(content)
    return await LlmSystemOneAdapter().evaluate(
        config=SystemOneConfigData(id=2, provider="llm", llm_data=LLM),
        state=STATE,
        questions=QUESTIONS,
    )


def test_the_llm_adapter_is_registered_next_to_typesafe():
    assert isinstance(SYSTEM_ONE_ADAPTERS["llm"], LlmSystemOneAdapter)
    assert "typesafe" in SYSTEM_ONE_ADAPTERS


@pytest.mark.asyncio
async def test_self_reported_probabilities_become_typesafe_shaped_answers(mock_completion):
    result, _ = await evaluate_with(json.dumps(LLM_ANSWER), mock_completion)

    assert result.answers["is_engineering"].noul == 0.92
    department = result.answers["department"]
    assert (department.choice, department.confidence) == ("engineering", 0.75)
    assert department.probabilities == {"engineering": 0.75, "sales": 0.25}
    seniority = result.answers["seniority"]
    assert seniority.score == pytest.approx(1.4)
    assert seniority.confidence == 0.5
    assert seniority.probabilities == {"0": 0.1, "1": 0.4, "2": 0.5}
    assert (result.provider, result.model_version) == ("llm", "gpt-4o-mini")


@pytest.mark.asyncio
@pytest.mark.parametrize("reported, expected", [(1.3, 1.0), (-0.2, 0.0), (0.4, 0.4)])
async def test_noul_outside_zero_to_one_is_clamped(mock_completion, reported, expected):
    content = with_answers(is_engineering={"noul": reported})

    result, _ = await evaluate_with(content, mock_completion)

    assert result.answers["is_engineering"].noul == expected


@pytest.mark.asyncio
async def test_probabilities_are_clamped_at_zero_and_filtered_to_the_asked_options(
    mock_completion,
):
    content = with_answers(
        department={"probabilities": {"engineering": -5, "sales": 2, "hr": 100}},
        seniority={"probabilities": {"0": 1, "2": 1, "7": 100}},
    )

    result, _ = await evaluate_with(content, mock_completion)

    department = result.answers["department"]
    assert (department.choice, department.confidence) == ("sales", 1.0)
    assert department.probabilities == {"engineering": 0.0, "sales": 1.0}
    seniority = result.answers["seniority"]
    assert seniority.probabilities == {"0": 0.5, "1": 0.0, "2": 0.5}
    assert seniority.score == pytest.approx(1.0)
    assert seniority.confidence == 0.5


@pytest.mark.asyncio
async def test_equal_top_probabilities_pick_the_first_option_in_criteria_order(mock_completion):
    content = with_answers(department={"probabilities": {"sales": 1, "engineering": 1}})

    result, _ = await evaluate_with(content, mock_completion)

    department = result.answers["department"]
    assert (department.choice, department.confidence) == ("engineering", 0.5)


@pytest.mark.asyncio
async def test_the_prompt_carries_the_same_json_state_typesafe_gets(mock_completion):
    await evaluate_with(json.dumps(LLM_ANSWER), mock_completion)

    kwargs = mock_completion.call_args.kwargs
    assert json.dumps(STATE, indent=2) in kwargs["messages"][-1]["content"]
    schema = kwargs["response_format"]["json_schema"]["schema"]
    answers = schema["properties"]["answers"]
    assert sorted(answers["required"]) == ["department", "is_engineering", "seniority"]
    assert answers["properties"]["is_engineering"]["required"] == ["noul"]
    seniority_keys = answers["properties"]["seniority"]["properties"]["probabilities"]["required"]
    assert seniority_keys == ["0", "1", "2"]


@pytest.mark.asyncio
async def test_an_answer_missing_a_question_is_a_system_one_error(mock_completion):
    content = json.dumps({"answers": {"is_engineering": {"noul": 0.5}}})

    with pytest.raises(SystemOneError) as error:
        await evaluate_with(content, mock_completion)

    assert str(error.value) == "The LLM returned no valid answer for 'department'."


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content, name",
    [
        ("I cannot answer that.", "is_engineering"),
        (json.dumps({"answers": []}), "is_engineering"),
        (with_answers(is_engineering={"noul": "high"}), "is_engineering"),
        (with_answers(is_engineering={"noul": True}), "is_engineering"),
        (with_answers(is_engineering={}), "is_engineering"),
        (
            with_answers(department={"probabilities": {"engineering": "a", "sales": 1}}),
            "department",
        ),
        (with_answers(department={"probabilities": {"engineering": 0, "sales": 0}}), "department"),
        (with_answers(department={"probabilities": {"hr": 1}}), "department"),
        (with_answers(department={"engineering": 1}), "department"),
        (with_answers(seniority={"probabilities": {"0": 0, "1": -3, "2": 0}}), "seniority"),
        (with_answers(seniority={"probabilities": {"0": None}}), "seniority"),
        pytest.param(
            with_answers(is_engineering={"noul": 10**400}), "is_engineering", id="huge-noul"
        ),
        pytest.param(
            with_answers(department={"probabilities": {"engineering": 10**400}}),
            "department",
            id="huge-probability",
        ),
    ],
)
async def test_a_malformed_answer_is_a_system_one_error_naming_the_question(
    mock_completion, content, name
):
    with pytest.raises(SystemOneError) as error:
        await evaluate_with(content, mock_completion)

    assert str(error.value) == f"The LLM returned no valid answer for '{name}'."


@pytest.mark.asyncio
async def test_a_provider_failure_does_not_leak_provider_text(mock_completion):
    mock_completion.side_effect = RuntimeError("provider said sk-live-123")

    with pytest.raises(SystemOneError) as error:
        await LlmSystemOneAdapter().evaluate(
            config=SystemOneConfigData(id=2, provider="llm", llm_data=LLM),
            state=STATE,
            questions=QUESTIONS,
        )

    assert str(error.value) == "The LLM call failed."
    assert "sk-live-123" not in str(error.value)
    assert isinstance(error.value.__cause__, RuntimeError)


@pytest.mark.asyncio
async def test_a_prompt_building_error_is_not_reported_as_an_llm_call_failure(mock_completion):
    with pytest.raises(TypeError):
        await LlmSystemOneAdapter().evaluate(
            config=SystemOneConfigData(id=2, provider="llm", llm_data=LLM),
            state={"when": object()},
            questions=QUESTIONS,
        )

    mock_completion.assert_not_called()


@pytest.mark.asyncio
async def test_a_config_without_an_llm_config_is_a_system_one_error(mock_completion):
    with pytest.raises(SystemOneError) as error:
        await LlmSystemOneAdapter().evaluate(
            config=SystemOneConfigData(id=2, provider="llm"), state=STATE, questions=QUESTIONS
        )

    assert str(error.value) == "This System One config has no LLM config."
    mock_completion.assert_not_called()


@pytest.mark.asyncio
async def test_usage_carries_the_litellm_cost(mock_completion):
    response = response_with(json.dumps(LLM_ANSWER))
    mock_completion.return_value = response

    _, usage = await LlmSystemOneAdapter().evaluate(
        config=SystemOneConfigData(id=2, provider="llm", llm_data=LLM),
        state=STATE,
        questions=QUESTIONS,
    )

    expected = litellm.completion_cost(completion_response=response)
    assert expected > 0
    assert usage.total_cost_usd == pytest.approx(expected)
    assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (50, 20, 70)


@pytest.mark.asyncio
async def test_model_version_is_the_llm_model(mock_completion):
    llm = LLMData(provider="openai", config=LLMConfigData(model="gpt-4o"))
    mock_completion.return_value = response_with(json.dumps(LLM_ANSWER))

    result, _ = await LlmSystemOneAdapter().evaluate(
        config=SystemOneConfigData(id=2, provider="llm", llm_data=llm),
        state=STATE,
        questions=QUESTIONS,
    )

    assert result.model_version == "gpt-4o"
