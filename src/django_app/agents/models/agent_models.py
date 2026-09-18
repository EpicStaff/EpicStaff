from django.db import models

from tables.models.base_models import AbstractDefaultFillableModel


class DefaultAgentDefinitionConfig(models.Model):
    """Singleton holding default values for AgentDefinition nullable fields."""

    max_iter = models.IntegerField(
        default=25,
        null=True,
        help_text="Default max reasoning iterations for an AgentDefinition when its own value is null.",
    )
    max_rpm = models.IntegerField(
        default=10,
        null=True,
        help_text="Default max LLM requests per minute when AgentDefinition.max_rpm is null.",
    )
    max_execution_time = models.IntegerField(
        default=60,
        null=True,
        help_text="Default per-run wall-clock budget in seconds when AgentDefinition.max_execution_time is null.",
    )
    cache = models.BooleanField(
        default=False,
        null=True,
        help_text="Default for whether tool-result caching is enabled when AgentDefinition.cache is null.",
    )
    max_retry_limit = models.IntegerField(
        default=3,
        null=True,
        help_text="Default max retries on transient failures when AgentDefinition.max_retry_limit is null.",
    )
    default_temperature = models.FloatField(
        default=0.7,
        null=True,
        help_text="Default sampling temperature applied when neither the AgentDefinition nor its LLMConfig specify one.",
    )
    max_tool_calls = models.IntegerField(
        default=15,
        null=True,
        help_text="Default max tool calls executed per agent run when AgentDefinition.max_tool_calls is null. Null = unlimited.",
    )
    tool_timeout = models.IntegerField(
        default=300,
        null=True,
        help_text="Default per-tool-call timeout in seconds when AgentDefinition.tool_timeout is null. Null = no timeout.",
    )
    max_consecutive_failures = models.IntegerField(
        default=3,
        null=True,
        help_text="Default consecutive tool-failure limit when AgentDefinition.max_consecutive_failures is null. Null = disabled.",
    )
    schema_max_retries = models.IntegerField(
        default=2,
        null=True,
        help_text="Default max schema-enforcement retries when AgentDefinition.schema_max_retries is null.",
    )

    @classmethod
    def load(cls) -> "DefaultAgentDefinitionConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __repr__(self) -> str:
        return f"DefaultAgentDefinitionConfig(pk={self.pk})"


class AgentDefinition(AbstractDefaultFillableModel):
    # Identity
    organization = models.ForeignKey(
        "tables.Organization",
        on_delete=models.CASCADE,
        related_name="agent_definitions",
        help_text="Organization this agent belongs to.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Stable identifier (slug-like) unique within an organization. Used to reference this agent from flows, code, and the UI.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Human-readable description of this agent — its purpose, persona, or capabilities. E.g. 'Senior Researcher focused on market analysis'.",
    )
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Free-form prompt for the agent. Put behavior, goals, tone, and constraints here.",
    )
    metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text="Free-form key-value store for arbitrary client/UI data. Not used by execution.",
    )

    # LLM linkage
    llm_config = models.ForeignKey(
        "tables.LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="agent_definitions",
        default=None,
        help_text="Primary LLM used for reasoning and tool selection.",
    )
    fcm_llm_config = models.ForeignKey(
        "tables.LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        related_name="fcm_agent_definitions",
        default=None,
        help_text="Optional dedicated LLM for function/tool-call routing. Falls back to llm_config when null.",
    )

    # Execution config
    max_iter = models.IntegerField(
        default=None,
        null=True,
        help_text="Max reasoning iterations per task before forcing a final answer. Null falls back to DefaultAgentDefinitionConfig.",
    )
    max_rpm = models.IntegerField(
        default=None,
        null=True,
        help_text="LLM request rate cap (requests per minute). Null falls back to DefaultAgentDefinitionConfig; no cap if both are null.",
    )
    max_execution_time = models.IntegerField(
        default=None,
        null=True,
        help_text="Wall-clock budget in seconds for a single agent run. Null falls back to DefaultAgentDefinitionConfig.",
    )
    cache = models.BooleanField(
        default=None,
        null=True,
        help_text="Enable tool-result caching for this agent. Null falls back to DefaultAgentDefinitionConfig.",
    )
    max_retry_limit = models.IntegerField(
        default=None,
        null=True,
        help_text="Max retries on transient LLM/tool failures. Null falls back to DefaultAgentDefinitionConfig.",
    )
    default_temperature = models.FloatField(
        default=None,
        null=True,
        help_text="Sampling temperature applied when the LLMConfig leaves it unset. Null falls back to DefaultAgentDefinitionConfig.",
    )
    max_tool_calls = models.IntegerField(
        default=None,
        null=True,
        help_text="Max tool calls executed per agent run. Null falls back to DefaultAgentDefinitionConfig.",
    )
    tool_timeout = models.IntegerField(
        default=None,
        null=True,
        help_text="Per-tool-call timeout in seconds. Null falls back to DefaultAgentDefinitionConfig.",
    )
    max_consecutive_failures = models.IntegerField(
        default=None,
        null=True,
        help_text="Consecutive failed tool calls before graceful stop. Null falls back to DefaultAgentDefinitionConfig.",
    )
    schema_max_retries = models.IntegerField(
        default=None,
        null=True,
        help_text="Max retries when enforcing structured-output schema validation. Null falls back to DefaultAgentDefinitionConfig.",
    )

    # Surface linkage (through AgentDefaultSurface)
    default_surface_list = models.ManyToManyField(
        "Surface",
        through="AgentDefaultSurface",
        related_name="default_in_agents",
        blank=True,
        help_text="Surfaces applied to this agent by default, per place (flow/chat/all). Managed via AgentDefaultSurface through table.",
    )

    def get_default_model(self):
        return DefaultAgentDefinitionConfig.load()

    def __repr__(self) -> str:
        return f"AgentDefinition(id={self.pk}, name={self.name!r})"

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="unique_agent_definition_name_per_organization",
            )
        ]


class SurfacePlace(models.TextChoices):
    ALL = "all", "All Places"
    FLOW = "flow", "Flow"
    CHAT = "chat", "Chat"
    REALTIME = "realtime", "Realtime"


class AgentDefaultSurface(models.Model):
    agent_definition = models.ForeignKey(
        AgentDefinition,
        on_delete=models.CASCADE,
        related_name="default_surfaces",
        help_text="Agent definition this default surface assignment belongs to.",
    )
    surface = models.ForeignKey(
        "Surface",
        on_delete=models.CASCADE,
        related_name="default_for",
        help_text="Surface assigned as the default for this agent in the given place.",
    )
    place = models.CharField(
        max_length=16,
        choices=SurfacePlace.choices,
        help_text="Context where this surface is the default: 'all' for any place, 'flow' for flow execution, 'chat' for chat sessions, 'realtime' for voice sessions.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent_definition", "surface", "place"],
                name="uniq_agent_default_surface",
            ),
        ]
