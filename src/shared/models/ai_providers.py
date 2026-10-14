from typing import Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

# Every level litellm knows, weakest first; the order is the one the UI lists them in.
# Which levels a given model accepts is decided per model in django_app
# (tables.utils.litellm_model_info.reasoning_support).
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
REASONING_EFFORT_VALUES: tuple[str, ...] = get_args(ReasoningEffort)

# Allowlist, not denylist: a transport field added to LLMConfigData later
# (credentials, endpoints, headers) must never leak into generation kwargs.
# A tuple keeps the kwargs order stable across processes.
LITELLM_GENERATION_FIELDS = (
    "temperature",
    "top_p",
    "stop",
    "max_tokens",
    "presence_penalty",
    "frequency_penalty",
    "logit_bias",
    "seed",
    "timeout",
    "reasoning_effort",
)


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
    extra_headers: dict[str, str] | None = None
    reasoning_effort: ReasoningEffort | None = None

    model_config = ConfigDict(from_attributes=True)

    def to_litellm_kwargs(self, exclude: set[str] | None = None) -> dict:
        """Return the generation parameters to pass to litellm, omitting unset ones.

        Generation params only. The model string, auth, base_url/api_version,
        deployment_id, extra_headers, store, response_format and tools stay with
        each caller.

        Args:
            exclude: Generation fields the caller must not send (e.g. a client
                that sets its own stop sequences or timeout).
        """
        excluded = exclude or set()
        return {
            name: value
            for name in LITELLM_GENERATION_FIELDS
            if name not in excluded and (value := getattr(self, name)) is not None
        }


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


class WebhookTriggerAuthData(BaseModel):
    kind: Literal["webhook", "telegram"]
    header_name: str
    secret: str | None = None


class BaseTunnelConfigData(BaseModel):
    name: str
    org_id: int | None = None

    auth: WebhookTriggerAuthData | None = None

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
