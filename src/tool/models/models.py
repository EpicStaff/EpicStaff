from typing import Any
from pydantic import BaseModel, HttpUrl


class ClassDataResponseModel(BaseModel):
    classdata: str


class RunToolResponseModel(BaseModel):
    data: str


class LLMConfig(BaseModel):
    model: str
    timeout: float | int | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop: str | list[str] | None = None
    max_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    logit_bias: dict[int, float] | None = None
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
