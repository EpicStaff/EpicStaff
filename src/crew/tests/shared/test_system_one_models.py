import pytest
from pydantic import ValidationError
from src.shared.models.system_one import (
    SYSTEM_ONE_QUESTIONS_ADAPTER,
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    SystemOneConfigData,
    SystemOneResult,
)
from src.shared.system_one.constants import (
    JEV_INPUT_PRICE_USD_PER_TOKEN,
    JEV_MODEL_VERSIONS,
    OPENAI_DECISIONS_MODELS,
    OPENAI_INPUT_PRICE_USD_PER_TOKEN,
)

NOUL = {"type": "noul", "instructions": "Is this an engineering company?"}


@pytest.mark.parametrize(
    "questions",
    [
        {"is_engineering": NOUL},
        {"is_engineering": {**NOUL, "criteria": {"true": "builds software", "false": "does not"}}},
        {
            "dept": {
                "type": "choice",
                "instructions": "Department",
                "criteria": {"eng": "Engineering", "ops": "Operations"},
            }
        },
        {
            "level": {
                "type": "score",
                "instructions": "Seniority",
                "criteria": ["junior", "mid", "senior"],
            }
        },
        pytest.param(
            {
                "dept": {
                    "type": "choice",
                    "instructions": "x",
                    "criteria": {f"o{i}": "d" for i in range(255)},
                }
            },
            id="choice-255-is-the-upper-limit",
        ),
        pytest.param(
            {"level": {"type": "score", "instructions": "x", "criteria": ["l"] * 10}},
            id="score-10-is-the-upper-limit",
        ),
        pytest.param(
            {"dept": {"type": "choice", "instructions": "x", "criteria": {"a": "d", "b": "d"}}},
            id="choice-2-is-the-lower-limit",
        ),
        pytest.param(
            {"level": {"type": "score", "instructions": "x", "criteria": ["low", "high"]}},
            id="score-2-is-the-lower-limit",
        ),
        pytest.param({f"q{i}": NOUL for i in range(400)}, id="400-questions-is-the-upper-limit"),
    ],
)
def test_valid_questions_are_accepted(questions):
    assert SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(questions)


@pytest.mark.parametrize(
    "questions",
    [
        pytest.param({}, id="no-questions"),
        pytest.param({"class": NOUL}, id="keyword-name"),
        pytest.param({"my-q": NOUL}, id="dash-name"),
        pytest.param({"1st": NOUL}, id="digit-first-name"),
        pytest.param({"__class__": NOUL}, id="dunder-name"),
        pytest.param({"_private": NOUL}, id="underscore-name"),
        pytest.param({"q": {**NOUL, "instructions": ""}}, id="empty-instructions"),
        pytest.param({"q": {**NOUL, "criteria": {"maybe": "x"}}}, id="noul-criteria-key"),
        pytest.param({"q": {**NOUL, "box": True}}, id="noul-unknown-field"),
        pytest.param(
            {"q": {"type": "choice", "instructions": "x", "criteria": {"a": "d", "b": "d"}, "box": True}},
            id="choice-unknown-field",
        ),
        pytest.param(
            {"q": {"type": "score", "instructions": "x", "criteria": ["l", "m"], "box": True}},
            id="score-unknown-field",
        ),
        pytest.param({"q": {"type": "box", "instructions": "x"}}, id="box-out-of-scope"),
        pytest.param({"q": {"type": "choice", "instructions": "x", "criteria": {}}}, id="choice-0"),
        pytest.param(
            {
                "q": {
                    "type": "choice",
                    "instructions": "x",
                    "criteria": {f"o{i}": "d" for i in range(256)},
                }
            },
            id="choice-256",
        ),
        pytest.param({"q": {"type": "score", "instructions": "x", "criteria": []}}, id="score-0"),
        pytest.param(
            {"q": {"type": "score", "instructions": "x", "criteria": ["l"] * 11}}, id="score-11"
        ),
        pytest.param(
            {"q": {"type": "choice", "instructions": "x", "criteria": {"a": "d"}}}, id="choice-1"
        ),
        pytest.param(
            {"q": {"type": "score", "instructions": "x", "criteria": ["l"]}}, id="score-1"
        ),
        pytest.param({f"q{i}": NOUL for i in range(401)}, id="401-questions"),
    ],
)
def test_invalid_questions_are_refused(questions):
    with pytest.raises(ValidationError):
        SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(questions)


def test_a_bad_question_name_is_named_in_the_error():
    with pytest.raises(ValidationError, match="my-q"):
        SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python({"my-q": NOUL})


def test_result_round_trips_through_json():
    result = SystemOneResult(
        answers={
            "is_engineering": NoulAnswer(type="noul", noul=0.9),
            "dept": ChoiceAnswer(
                type="choice", choice="eng", confidence=0.8, probabilities={"eng": 0.8, "ops": 0.2}
            ),
            "level": ScoreAnswer(
                type="score",
                score=2.0,
                confidence=0.7,
                probabilities={"0": 0.1, "1": 0.2, "2": 0.7},
            ),
        },
        provider="typesafe",
        model_version="jev-1.14.0",
    )

    assert SystemOneResult.model_validate_json(result.model_dump_json()) == result


def test_config_data_never_dumps_the_secret_id():
    config = SystemOneConfigData(id=1, provider="typesafe", api_key_secret_id=7)

    assert "api_key_secret_id" not in config.model_dump()


@pytest.mark.parametrize("value", [0, 1])
def test_answer_values_at_the_range_limits_are_accepted(value):
    NoulAnswer(type="noul", noul=value)
    ChoiceAnswer(type="choice", choice="a", confidence=value, probabilities={"a": value})
    ScoreAnswer(type="score", score=1, confidence=value, probabilities={"0": value})


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda: NoulAnswer(type="noul", noul=85), id="noul-percent"),
        pytest.param(
            lambda: ChoiceAnswer(type="choice", choice="a", confidence=1.5, probabilities={"a": 1}),
            id="choice-confidence",
        ),
        pytest.param(
            lambda: ChoiceAnswer(type="choice", choice="a", confidence=1, probabilities={"a": 1.5}),
            id="choice-probability",
        ),
        pytest.param(
            lambda: ScoreAnswer(type="score", score=1, confidence=-0.1, probabilities={"0": 1}),
            id="score-confidence",
        ),
        pytest.param(
            lambda: ScoreAnswer(type="score", score=1, confidence=1, probabilities={"0": 1.5}),
            id="score-probability",
        ),
    ],
)
def test_answer_values_outside_zero_to_one_are_refused(build):
    with pytest.raises(ValidationError):
        build()


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf")])
def test_a_score_that_is_not_a_finite_number_is_refused(score):
    with pytest.raises(ValidationError):
        ScoreAnswer(type="score", score=score, confidence=1, probabilities={"0": 1})


def test_score_is_not_limited_to_zero_to_one():
    assert ScoreAnswer(type="score", score=2.4, confidence=1, probabilities={"2": 1}).score == 2.4


def test_every_pinned_jev_version_has_a_price():
    assert set(JEV_MODEL_VERSIONS) == set(JEV_INPUT_PRICE_USD_PER_TOKEN)


def test_every_pinned_openai_model_has_a_price():
    assert set(OPENAI_DECISIONS_MODELS) == set(OPENAI_INPUT_PRICE_USD_PER_TOKEN)


def test_config_repr_hides_the_key():
    config = SystemOneConfigData(id=1, provider="typesafe", api_key="ts-key")

    assert "ts-key" not in repr(config)
