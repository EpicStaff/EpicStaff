from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from tables.models.base_models import (
    AbstractDefaultFillableModel,
    SoftDeleteFields,
    SoftDeleteMixin,
    soft_delete_consistency_constraint,
)
from tables.validators.finite_number_validator import validate_finite_number


class DefaultAgentDefinitionConfig(models.Model):
    """Singleton holding default values for AgentDefinition nullable fields."""

    default_temperature = models.FloatField(
        default=0.7,
        null=True,
        help_text="Default sampling temperature applied when neither the AgentDefinition nor its LLMConfig specify one.",
    )

    @classmethod
    def load(cls) -> "DefaultAgentDefinitionConfig":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def __repr__(self) -> str:
        return f"DefaultAgentDefinitionConfig(pk={self.pk})"


class AgentDefinition(AbstractDefaultFillableModel, SoftDeleteMixin):
    # Identity
    organization = models.ForeignKey(
        "rbac.Organization",
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
    instruction_list = models.JSONField(
        default=list,
        blank=True,
        help_text='Ordered list of named prompt instructions, each {"name": str, "content": str}. Applied to the agent in list order; put behavior, goals, tone, and constraints here.',
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
        default=15,
        validators=[MinValueValidator(1), MaxValueValidator(90)],
        help_text="Max reasoning iterations per task before forcing a final answer.",
    )
    max_rpm = models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(240)],
        help_text="LLM request rate cap (requests per minute).",
    )
    max_execution_time = models.IntegerField(
        default=600,
        validators=[MinValueValidator(60), MaxValueValidator(1800)],
        help_text="Wall-clock budget in seconds for a single agent run.",
    )
    cache = models.BooleanField(
        default=False,
        help_text="Enable tool-result caching for this agent.",
    )
    max_retry_limit = models.IntegerField(
        default=3,
        validators=[MinValueValidator(0), MaxValueValidator(10)],
        help_text="Max retries on transient LLM/tool failures.",
    )
    default_temperature = models.FloatField(
        default=None,
        null=True,
        validators=[validate_finite_number, MinValueValidator(0.0), MaxValueValidator(2.0)],
        help_text="Sampling temperature applied when the LLMConfig leaves it unset. Null falls back to DefaultAgentDefinitionConfig.",
    )
    max_tool_calls = models.IntegerField(
        default=15,
        validators=[MinValueValidator(1), MaxValueValidator(300)],
        help_text="Max tool calls executed per agent run.",
    )
    tool_timeout = models.IntegerField(
        default=300,
        validators=[MinValueValidator(10), MaxValueValidator(1800)],
        help_text="Per-tool-call timeout in seconds.",
    )
    max_consecutive_failures = models.IntegerField(
        default=3,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
        help_text="Consecutive failed tool calls before graceful stop.",
    )
    schema_max_retries = models.IntegerField(
        default=2,
        validators=[MinValueValidator(0), MaxValueValidator(20)],
        help_text="Max retries when enforcing structured-output schema validation.",
    )

    # Surface linkage (through AgentDefaultSurface)
    default_surface_list = models.ManyToManyField(
        "Surface",
        through="AgentDefaultSurface",
        related_name="default_in_agents",
        blank=True,
        help_text="Surfaces applied to this agent by default, per place (flow/chat/all). Managed via AgentDefaultSurface through table.",
    )

    @property
    def instructions(self) -> str:
        """Return the non-blank instruction contents joined in application order."""
        return "\n\n".join(
            instruction["content"]
            for instruction in self.instruction_list
            if instruction["content"].strip()
        )

    def get_default_model(self):
        return DefaultAgentDefinitionConfig.load()

    def __repr__(self) -> str:
        return f"AgentDefinition(id={self.pk}, name={self.name!r})"

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["organization", "name"],
                condition=models.Q(active=True),
                name="unique_agent_definition_name_per_organization",
            ),
        ]


class SurfacePlace(models.TextChoices):
    ALL = "all", "All Places"
    FLOW = "flow", "Flow"
    CHAT = "chat", "Chat"
    REALTIME = "realtime", "Realtime"


class AgentDefaultSurface(SoftDeleteFields, models.Model):
    soft_delete_reference_fields = ("surface",)
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
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["agent_definition", "surface", "place"],
                name="uniq_agent_default_surface",
            ),
        ]

    @classmethod
    def soft_delete_owned_references(cls, field_name: str, target) -> models.Q | None:
        """Rows reached through a reference field that still belong to the target.

        A surface owns its owner agent's default-surface rows for it: they go to
        the recycle bin with the surface, so a restore keeps the places the owner
        chose instead of falling back to "applies everywhere". Other agents' rows
        stay references and are removed. Restore is an undo: rows the owner adds
        while the surface is binned stay next to the restored ones.
        """
        if field_name == "surface" and target.owner_agent_id is not None:
            return models.Q(agent_definition_id=target.owner_agent_id)
        return None
