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
    org_id: int | None = None
    auths: list[WebhookNodeAuthData] = []
    has_unauthenticated_node: bool = False

    @classmethod
    def _tunnel_prefix(cls) -> str:
        return "base"

    @property
    def unique_id(self) -> str:
        """`"<provider>:<org_id>:<path-name>"`.

        The `org_id` segment is load-bearing, not cosmetic: it is the only
        thing that keeps two different orgs' tunnel configs from colliding
        on the same registry/Redis key when they happen to choose an
        identical `path` (see `org_id` docstring above). `org_id=None`
        renders as the literal string `"none"` -- kept distinguishable from
        a real id rather than silently collapsing to the pre-org-aware
        2-part format.
        """
        org_segment = "none" if self.org_id is None else str(self.org_id)
        return f"{self.__class__._tunnel_prefix()}:{org_segment}:{self.name}"


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
