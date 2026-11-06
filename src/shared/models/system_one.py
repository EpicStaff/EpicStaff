import keyword
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, TypeAdapter

from .ai_providers import LLMData

LLM_PROMPT_KIND = "llm"
SYSTEM_ONE_PROMPT_KIND = "system_one"
PromptKind = Literal["llm", "system_one"]


class NoulQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["noul"]
    instructions: str = Field(min_length=1)
    criteria: dict[Literal["true", "false"], str] | None = None


class ChoiceQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["choice"]
    instructions: str = Field(min_length=1)
    criteria: dict[str, str] = Field(min_length=2, max_length=255)  # option -> description


class ScoreQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["score"]
    instructions: str = Field(min_length=1)
    criteria: list[str] = Field(min_length=2, max_length=10)  # ordered levels; index = score


SystemOneQuestion = Annotated[
    NoulQuestion | ChoiceQuestion | ScoreQuestion, Field(discriminator="type")
]


def _require_identifier_names(questions: dict) -> dict:
    for name in questions:
        if not name.isidentifier() or keyword.iskeyword(name) or name.startswith("_"):
            raise ValueError(
                f"Question name '{name}' must be a Python identifier that does not start with "
                f"an underscore: conditions read it as answers.{name}."
            )
    return questions


MAX_SYSTEM_ONE_QUESTIONS = 400

SystemOneQuestions = Annotated[
    dict[str, SystemOneQuestion],
    Field(min_length=1, max_length=MAX_SYSTEM_ONE_QUESTIONS),
    AfterValidator(_require_identifier_names),
]
SYSTEM_ONE_QUESTIONS_ADAPTER = TypeAdapter(SystemOneQuestions)


Probability = Annotated[float, Field(ge=0, le=1)]


class NoulAnswer(BaseModel):
    type: Literal["noul"]
    noul: Probability


class ChoiceAnswer(BaseModel):
    type: Literal["choice"]
    choice: str
    confidence: Probability
    probabilities: dict[str, Probability]


class ScoreAnswer(BaseModel):
    type: Literal["score"]
    score: float
    confidence: Probability
    probabilities: dict[str, Probability]


SystemOneAnswer = Annotated[NoulAnswer | ChoiceAnswer | ScoreAnswer, Field(discriminator="type")]


class SystemOneResult(BaseModel):
    """What a System One entry stores under its result variable; rows read `answers.<name>.<field>`."""

    answers: dict[str, SystemOneAnswer]
    provider: str
    model_version: str


class SystemOneConfigData(BaseModel):
    """A System One config as crew receives it; SecretResolver fills `api_key` from `api_key_secret_id`."""

    id: int
    provider: str  # a str, not a Literal: the adapter registry decides which providers exist
    model_name: str | None = None
    api_key: str | None = Field(default=None, repr=False)
    api_key_secret_id: int | None = Field(default=None, exclude=True)
    llm_data: LLMData | None = None
