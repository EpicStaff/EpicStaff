from pydantic import BaseModel
from typing import Literal, Optional
from pydantic import ConfigDict, Field


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
    seed: int | None = None
    base_url: str | None = None
    api_version: str | None = None
    api_key: str | None = None
    api_key_secret_id: int | None = Field(default=None, exclude=True)
    """In-memory carrier for SecretResolver; excluded from every dump so no
    Secret id reaches Session.graph_schema or the Redis payload."""
    deployment_id: str | None = None
    headers: dict[str, str] | None = None
    extra_headers: dict[str, str] | None = None

    model_config = ConfigDict(from_attributes=True)


class EmbedderConfigData(BaseModel):
    model: str
    deployment_name: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    api_key_secret_id: int | None = Field(default=None, exclude=True)

    model_config = ConfigDict(from_attributes=True)


class LLMData(BaseModel):
    provider: str
    config: LLMConfigData

    model_config = ConfigDict(from_attributes=True)


class EmbedderData(BaseModel):
    provider: str
    config: EmbedderConfigData

    model_config = ConfigDict(from_attributes=True)


class WebhookNodeAuthData(BaseModel):
    enabled: bool = True
    scheme: str
    header_name: str
    timestamp_header_name: Optional[str] = None
    tolerance_seconds: int = 300
    secret_hash: Optional[str] = None
    signing_secret: Optional[str] = None
    # Stable identifier of the single node this credential belongs to, e.g.
    # "tables.telegramtriggernode:42" / "tables.webhooktriggernode:17"
    # (Django's own `_meta.label_lower` + pk). The `webhook` service echoes
    # this back as `WebhookEventData.auth_principal` once this credential
    # matches, so Django's `webhook_events_handler` can restrict dispatch to
    # only the node that owns the matched credential.
    principal: Optional[str] = None


class BaseTunnelConfigData(BaseModel):
    name: str
    auths: list[WebhookNodeAuthData] = []
    # True when at least one node attached to this trigger/path has NO
    # enabled auth configured (e.g. a generic webhook node with auth
    # disabled, sharing a path with a Telegram node that has mandatory
    # auth). When True, `webhook_routes.handle_webhook` must let an
    # unauthenticated request through (scoped only to the auth-free
    # node(s) via `UNAUTHENTICATED_FALLBACK_PRINCIPAL`) instead of
    # rejecting with 401, even though `auths` is non-empty. Defaults to
    # `False` for backward compatibility with any wire payload minted
    # before this field existed.
    has_unauthenticated_node: bool = False

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


class LocalhostConfigData(BaseTunnelConfigData):
    domain: str | None = None

    @classmethod
    def _tunnel_prefix(cls) -> str:
        return "localhost"


class WebhookConfigData(BaseModel):
    ngrok_configs: list[NgrokConfigData] = []
    localhost_configs: list[LocalhostConfigData] = []
    # other configs
    ...
