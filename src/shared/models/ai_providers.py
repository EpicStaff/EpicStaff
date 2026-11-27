from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

# Every level litellm knows, weakest first; the order is the one the UI lists them in.
# Which levels a given model accepts is decided per model in django_app
# (ai_models.utils.litellm_model_info.reasoning_support).
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
REASONING_EFFORT_VALUES: tuple[str, ...] = get_args(ReasoningEffort)

_AZURE_DEPLOYMENT_ARGUMENT = "deployment_id"


class LLMConfigData(BaseModel):
    """LLM settings a run sends to the agent and crew services.

    The token prices are cost-only and are never forwarded to litellm's completion
    call, which would treat them as custom pricing and register them in its
    process-wide price map.
    """

    model: str
    custom_name: str | None = None
    """Display name of the LLMConfig this was built from. Used to label which
    config served a run; never sent to litellm."""
    timeout: float | int | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    """The model's settings as litellm keyword arguments (`temperature`, `max_tokens`...),
    already limited by django_app to the ones the model catalog allows."""
    connection: dict[str, str] = Field(default_factory=dict, repr=False)
    """Provider connection arguments under their litellm names (`api_base`,
    `aws_region_name`...). SecretResolver fills its `epicstaff_secret(<name>)` markers,
    so a resolved copy holds secrets: never log it."""
    main_secret_argument: str = "api_key"
    """The litellm argument `api_key` is sent as for this provider."""
    api_key: str | None = Field(default=None, repr=False)
    api_key_secret_id: int | None = Field(default=None, exclude=True)
    """In-memory carrier for SecretResolver; excluded from every dump so no
    Secret id reaches the Redis payload or anything persisted from this model."""
    extra_headers: dict[str, str] | None = None
    input_cost_per_token: float | None = None
    """USD per prompt token. Used for cost, together with output_cost_per_token,
    instead of litellm's price map; null means litellm's price map."""
    output_cost_per_token: float | None = None
    """USD per completion token. Used for cost, together with input_cost_per_token,
    instead of litellm's price map; null means litellm's price map."""

    model_config = ConfigDict(from_attributes=True)

    def connection_kwargs(self) -> dict[str, str]:
        """Return the connection arguments and the main secret for a litellm call.

        `deployment_id` is left out: it only names the model of an Azure config
        (`litellm_call_model`), and litellm sends any call carrying it to Azure.
        Holds the resolved secrets: never log it or put it in an error message.
        """
        return _connection_kwargs(self.connection, self.main_secret_argument, self.api_key)


def _connection_kwargs(
    connection: dict[str, str], main_secret_argument: str, api_key: str | None
) -> dict[str, str]:
    # An empty field is "not set": litellm then falls back to its own default.
    kwargs = {
        name: value
        for name, value in connection.items()
        if value and name != _AZURE_DEPLOYMENT_ARGUMENT
    }
    if api_key:
        kwargs[main_secret_argument] = api_key
    return kwargs


class EmbedderConfigData(BaseModel):
    """Embedding settings a run sends; `parameters` and `connection` as on LLMConfigData."""

    model: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    connection: dict[str, str] = Field(default_factory=dict, repr=False)
    main_secret_argument: str = "api_key"
    api_key: str | None = Field(default=None, repr=False)
    api_key_secret_id: int | None = Field(default=None, exclude=True)
    extra_headers: dict[str, str] | None = None

    model_config = ConfigDict(from_attributes=True)

    def connection_kwargs(self) -> dict[str, str]:
        """Return the connection arguments and the main secret for a litellm call.

        `deployment_id` is left out: it only names the model of an Azure config
        (`litellm_call_model`), and litellm sends any call carrying it to Azure.
        Holds the resolved secrets: never log it or put it in an error message.
        """
        return _connection_kwargs(self.connection, self.main_secret_argument, self.api_key)


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
