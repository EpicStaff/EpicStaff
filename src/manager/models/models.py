from typing import Any
from enum import Enum
from pydantic import BaseModel, HttpUrl


# TODO we use session status in the manager and crew, so we should move it to a shared location
#  look at SessionCallbackFactory in crew
class SessionStatus(Enum):
    END = "end"
    RUN = "run"
    WAIT_FOR_USER = "wait_for_user"
    ERROR = "error"


class RunCrewModel(BaseModel):
    data: dict[str, Any]


class ToolListResponseModel(BaseModel):
    tool_list: list[str]


class ClassDataResponseModel(BaseModel):
    classdata: str


class RunToolResponseModel(BaseModel):
    data: str


class RunCrewResponseModel(BaseModel):
    data: str


class LLMConfig(BaseModel):
    model: str
    stream: bool = True
    timeout: float | int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[int, float] | None = None
    response_format: dict[str, Any] | None = None
    seed: int | None = None
    logprobs: bool | None = None
    top_logprobs: int | None = None
    base_url: str | None = None
    api_version: str | None = None
    api_key: str | None = None


class EmbedderConfig(BaseModel):
    model: str
    deployment_name: str | None = None
    base_url: HttpUrl | None = None
    api_key: str | None = None


class LLMData(BaseModel):
    provider: str
    config: LLMConfig


class EmbedderData(BaseModel):
    provider: str
    config: EmbedderConfig


class ToolConfig(BaseModel):
    llm: LLMData | None = None
    embedder: EmbedderData | None = None
    tool_init_configuration: dict[str, Any] | None = None


class RunToolParamsModel(BaseModel):
    tool_config: ToolConfig | None = None
    run_kwargs: dict[str, Any]


class ToolInitConfigurationModel(BaseModel):
    tool_init_configuration: dict[str, Any] | None = None
