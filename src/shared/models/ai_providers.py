from pydantic import BaseModel
from typing import Any, Literal
from pydantic import ConfigDict, HttpUrl


class LLMConfigData(BaseModel):
    model: str
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
    base_url: str | None = None
    api_version: str | None = None
    api_key: str | None = None
    deployment_id: str | None = None
    headers: dict[str, str] | None = None
    extra_headers: dict[str, str] | None = None

    model_config = ConfigDict(from_attributes=True)


class EmbedderConfigData(BaseModel):
    model: str
    deployment_name: str | None = None
    base_url: HttpUrl | None = None
    api_key: str | None = None

    model_config = ConfigDict(from_attributes=True)


class LLMData(BaseModel):
    provider: str
    config: LLMConfigData

    model_config = ConfigDict(from_attributes=True)


class EmbedderData(BaseModel):
    provider: str
    config: EmbedderConfigData

    model_config = ConfigDict(from_attributes=True)


class BaseTunnelConfigData(BaseModel):
    name: str

    @classmethod
    def _tunnel_prefix(cls):
        return "base"

    @property
    def unique_id(self):
        return f"{self.__class__._tunnel_prefix()}:{self.name}"


class NgrokConfigData(BaseTunnelConfigData):
    auth_token: str
    domain: str | None = None
    region: Literal["us", "eu", "ap"] | None = None

    @classmethod
    def _tunnel_prefix(cls) -> str:
        return "ngrok"


class WebhookConfigData(BaseModel):
    ngrok_configs: list[NgrokConfigData]
    # other configs
    ...
