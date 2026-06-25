from __future__ import annotations

from django.db import models

from tables.models.base_models import TimestampMixin


class ToolMode(models.TextChoices):
    ALLOW = "allow"
    DENY = "deny"


class StorageAccess(models.TextChoices):
    ALLOW = "allow"  # explicitly allowed (was True)
    UNSET = "unset"  # default — neither granted nor forbidden (was False)
    DENY = "deny"  # explicitly forbidden — hard deny, overrides any grant


class Surface(TimestampMixin, models.Model):
    organization = models.ForeignKey(
        "Organization",
        on_delete=models.CASCADE,
        related_name="surfaces",
        help_text="Organization this surface belongs to.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Stable identifier unique within the organization. Used as the user-facing name for this surface.",
    )
    description = models.TextField(
        blank=True,
        default="",
        help_text="Optional human-readable description shown in the UI. Empty string means no description.",
    )
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Free-form text appended to the agent prompt when this surface is active. Empty string means no extra instructions.",
    )
    owner_agent = models.ForeignKey(
        "AgentDefinition",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
        related_name="owned_surfaces",
        help_text="Agent that owns this surface. Null means shared — any agent or place may use it. Set means agent-specific — only that agent.",
    )
    allow_creation = models.BooleanField(
        default=False,
        help_text="Surface-wide permission: when True, the agent may create new storage files within this surface.",
    )

    class Meta(TimestampMixin.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_surface_org_name",
            ),
        ]

    def __repr__(self) -> str:
        return f"Surface(id={self.pk}, name={self.name!r})"


class SurfacePythonTool(models.Model):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="python_tools",
        help_text="Surface this entry belongs to.",
    )
    python_tool = models.ForeignKey(
        "PythonCodeTool",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="PythonCodeTool being allowed or denied on this surface.",
    )
    mode = models.CharField(
        max_length=5,
        choices=ToolMode.choices,
        help_text="Whether this tool is explicitly allowed or denied for this surface.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "python_tool"],
                name="uniq_surface_python_tool",
            ),
        ]


class SurfaceMcpTool(models.Model):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="mcp_tools",
        help_text="Surface this entry belongs to.",
    )
    mcp_tool = models.ForeignKey(
        "McpTool",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="McpTool being allowed or denied on this surface.",
    )
    mode = models.CharField(
        max_length=5,
        choices=ToolMode.choices,
        help_text="Whether this tool is explicitly allowed or denied for this surface.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "mcp_tool"],
                name="uniq_surface_mcp_tool",
            ),
        ]


class SurfaceStorageItem(models.Model):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="storage_items",
        help_text="Surface this storage permission entry belongs to.",
    )
    storage_file = models.ForeignKey(
        "StorageFile",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="StorageFile whose access is being configured for this surface.",
    )
    can_list = models.CharField(
        max_length=5,
        choices=StorageAccess.choices,
        default=StorageAccess.UNSET,
        help_text="Whether the agent may list (enumerate) this file/folder. 'deny' explicitly forbids it.",
    )
    can_view = models.CharField(
        max_length=5,
        choices=StorageAccess.choices,
        default=StorageAccess.UNSET,
        help_text="Whether the agent may read/view the content of this file. 'deny' explicitly forbids it.",
    )
    can_edit = models.CharField(
        max_length=5,
        choices=StorageAccess.choices,
        default=StorageAccess.UNSET,
        help_text="Whether the agent may modify or overwrite this file. 'deny' explicitly forbids it.",
    )
    can_delete = models.CharField(
        max_length=5,
        choices=StorageAccess.choices,
        default=StorageAccess.UNSET,
        help_text="Whether the agent may delete this file. 'deny' explicitly forbids it.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "storage_file"],
                name="uniq_surface_storage_item",
            ),
        ]


class SurfaceKnowledge(models.Model):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="knowledge",
        help_text="Surface this knowledge collection is attached to.",
    )
    collection = models.ForeignKey(
        "SourceCollection",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="SourceCollection available within this surface.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "collection"],
                name="uniq_surface_knowledge",
            ),
        ]


class SurfaceNaiveSearchConfig(models.Model):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="naive_search_config",
        help_text="SurfaceKnowledge entry this naive search configuration applies to.",
    )
    search_limit = models.PositiveIntegerField(
        default=3,
        blank=True,
        help_text="Integer between 0 and 1000 for knowledge",
    )
    similarity_threshold = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.2,
        blank=True,
        help_text="Float between 0.00 and 1.00 for knowledge",
    )


class SurfaceGraphBasicSearchConfig(models.Model):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_basic_search_config",
        help_text="SurfaceKnowledge entry this GraphRAG basic search configuration applies to.",
    )
    prompt = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text="The basic search prompt to use.",
    )
    k = models.IntegerField(
        default=10,
        help_text="The number of text units to include in search context.",
    )
    max_context_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum tokens.",
    )


class SurfaceGraphLocalSearchConfig(models.Model):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_local_search_config",
        help_text="SurfaceKnowledge entry this GraphRAG local search configuration applies to.",
    )
    prompt = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text="The local search prompt to use.",
    )
    text_unit_prop = models.FloatField(
        default=0.5,
        help_text="The text unit proportion.",
    )
    community_prop = models.FloatField(
        default=0.15,
        help_text="The community proportion.",
    )
    conversation_history_max_turns = models.IntegerField(
        default=5,
        help_text="The conversation history maximum turns.",
    )
    top_k_entities = models.IntegerField(
        default=10,
        help_text="The top k mapped entities.",
    )
    top_k_relationships = models.IntegerField(
        default=10,
        help_text="The top k mapped relations.",
    )
    max_context_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum tokens.",
    )
