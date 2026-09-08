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
        "tables.Organization",
        on_delete=models.CASCADE,
        related_name="surfaces",
        help_text="Organization this surface belongs to.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Stable identifier unique within the organization. Used as the user-facing name for this surface.",
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

    class Meta(TimestampMixin.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "name"],
                name="uniq_surface_org_name",
            ),
        ]

    def __repr__(self) -> str:
        return f"Surface(id={self.pk}, name={self.name!r})"


class BaseSurfacePythonTool(models.Model):
    python_tool = models.ForeignKey(
        "tables.PythonCodeTool",
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
        abstract = True


class SurfacePythonTool(BaseSurfacePythonTool):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="python_tools",
        help_text="Surface this entry belongs to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "python_tool"],
                name="uniq_surface_python_tool",
            ),
        ]


class BaseSurfaceMcpTool(models.Model):
    mcp_tool = models.ForeignKey(
        "tables.McpTool",
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
        abstract = True


class SurfaceMcpTool(BaseSurfaceMcpTool):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="mcp_tools",
        help_text="Surface this entry belongs to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "mcp_tool"],
                name="uniq_surface_mcp_tool",
            ),
        ]


class BaseSurfaceStorageItem(models.Model):
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
        abstract = True


class SurfaceStorageItem(BaseSurfaceStorageItem):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="storage_items",
        help_text="Surface this storage permission entry belongs to.",
    )
    storage_file = models.ForeignKey(
        "tables.StorageFile",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="StorageFile whose access is being configured for this surface.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "storage_file"],
                name="uniq_surface_storage_item",
            ),
        ]


class BaseSurfaceKnowledge(models.Model):
    collection = models.ForeignKey(
        "tables.SourceCollection",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="SourceCollection available within this surface.",
    )

    class Meta:
        abstract = True


class SurfaceKnowledge(BaseSurfaceKnowledge):
    surface = models.ForeignKey(
        Surface,
        on_delete=models.CASCADE,
        related_name="knowledge",
        help_text="Surface this knowledge collection is attached to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["surface", "collection"],
                name="uniq_surface_knowledge",
            ),
        ]


class BaseSurfaceNaiveSearchConfig(models.Model):
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
    is_suggested = models.BooleanField(
        default=False,
        help_text="Whether these values came from parameter suggestion.",
    )

    class Meta:
        abstract = True


class SurfaceNaiveSearchConfig(BaseSurfaceNaiveSearchConfig):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="naive_search_config",
        help_text="SurfaceKnowledge entry this naive search configuration applies to.",
    )


class BaseSurfaceGraphBasicSearchConfig(models.Model):
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
    is_suggested = models.BooleanField(
        default=False,
        help_text="Whether these values came from parameter suggestion.",
    )

    class Meta:
        abstract = True


class SurfaceGraphBasicSearchConfig(BaseSurfaceGraphBasicSearchConfig):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_basic_search_config",
        help_text="SurfaceKnowledge entry this GraphRAG basic search configuration applies to.",
    )


class BaseSurfaceGraphLocalSearchConfig(models.Model):
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
    is_suggested = models.BooleanField(
        default=False,
        help_text="Whether these values came from parameter suggestion.",
    )

    class Meta:
        abstract = True


class SurfaceGraphLocalSearchConfig(BaseSurfaceGraphLocalSearchConfig):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_local_search_config",
        help_text="SurfaceKnowledge entry this GraphRAG local search configuration applies to.",
    )


class BaseSurfaceGraphGlobalSearchConfig(models.Model):
    map_prompt = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text="The map-step prompt used to answer the query against each community report batch.",
    )
    reduce_prompt = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text="The reduce-step prompt used to aggregate map answers into the final response.",
    )
    knowledge_prompt = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text="The general-knowledge prompt supplying background context to the search.",
    )
    max_context_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum tokens for the overall search context window.",
    )
    data_max_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum tokens of community-report data passed into the map step.",
    )
    map_max_length = models.IntegerField(
        default=1000,
        help_text="The maximum length (in words) of each map-step response.",
    )
    reduce_max_length = models.IntegerField(
        default=2000,
        help_text="The maximum length (in words) of the reduce-step response.",
    )
    dynamic_community_selection = models.BooleanField(
        default=False,
        help_text="Whether to let an LLM rate and dynamically select relevant communities instead of using all of them.",
    )
    dynamic_search_threshold = models.IntegerField(
        default=1,
        help_text="The minimum LLM relevance rating a community must reach to be included in dynamic selection.",
    )
    dynamic_search_keep_parent = models.BooleanField(
        default=False,
        help_text="Whether to keep a parent community when any of its child communities are rated relevant.",
    )
    dynamic_search_num_repeats = models.IntegerField(
        default=1,
        help_text="The number of times each community is rated during dynamic selection (ratings are averaged).",
    )
    dynamic_search_use_summary = models.BooleanField(
        default=False,
        help_text="Whether to rate communities using their summary instead of the full report content.",
    )
    dynamic_search_max_level = models.IntegerField(
        default=2,
        help_text="The maximum community hierarchy level to consider during dynamic selection.",
    )
    is_suggested = models.BooleanField(
        default=False,
        help_text="Whether these values came from parameter suggestion.",
    )

    class Meta:
        abstract = True


class SurfaceGraphGlobalSearchConfig(BaseSurfaceGraphGlobalSearchConfig):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_global_search_config",
        help_text="SurfaceKnowledge entry this GraphRAG global search configuration applies to.",
    )


class BaseSurfaceGraphDriftSearchConfig(models.Model):
    prompt = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text="The primer prompt used to seed the initial answer and follow-up questions.",
    )
    reduce_prompt = models.TextField(
        null=True,
        blank=True,
        default=None,
        help_text="The reduce-step prompt used to aggregate traversal results into the final answer.",
    )
    data_max_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum tokens of context data passed into the search.",
    )
    reduce_max_tokens = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="The maximum context tokens for the reduce step (None uses the model default).",
    )
    reduce_temperature = models.FloatField(
        default=0.0,
        help_text="The sampling temperature for the reduce-step LLM call.",
    )
    reduce_max_completion_tokens = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="The maximum completion tokens the reduce step may generate (None uses the model default).",
    )
    concurrency = models.IntegerField(
        default=32,
        help_text="The number of concurrent LLM requests during traversal.",
    )
    drift_k_followups = models.IntegerField(
        default=20,
        help_text="The number of follow-up questions to keep and explore at each step.",
    )
    primer_folds = models.IntegerField(
        default=5,
        help_text="The number of folds the community reports are split into for the primer step.",
    )
    primer_llm_max_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum tokens for each primer LLM call.",
    )
    n_depth = models.IntegerField(
        default=3,
        help_text="The number of traversal iterations (depth) of follow-up exploration.",
    )
    community_level = models.IntegerField(
        default=2,
        help_text="The community hierarchy level whose reports are used for the primer.",
    )
    local_search_text_unit_prop = models.FloatField(
        default=0.9,
        help_text="The text unit proportion for the local searches spawned during traversal.",
    )
    local_search_community_prop = models.FloatField(
        default=0.1,
        help_text="The community proportion for the local searches spawned during traversal.",
    )
    local_search_top_k_mapped_entities = models.IntegerField(
        default=10,
        help_text="The top k mapped entities for the local searches spawned during traversal.",
    )
    local_search_top_k_relationships = models.IntegerField(
        default=10,
        help_text="The top k mapped relations for the local searches spawned during traversal.",
    )
    local_search_max_data_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum context tokens for the local searches spawned during traversal.",
    )
    local_search_temperature = models.FloatField(
        default=0.0,
        help_text="The sampling temperature for the local-search LLM calls.",
    )
    local_search_top_p = models.FloatField(
        default=1.0,
        help_text="The nucleus sampling top-p for the local-search LLM calls.",
    )
    local_search_n = models.IntegerField(
        default=1,
        help_text="The number of completions to generate per local-search LLM call.",
    )
    local_search_llm_max_gen_tokens = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="The maximum tokens a local-search call may generate (None uses the model default).",
    )
    local_search_llm_max_gen_completion_tokens = models.IntegerField(
        null=True,
        blank=True,
        default=None,
        help_text="The maximum completion tokens a local-search call may generate (None uses the model default).",
    )
    is_suggested = models.BooleanField(
        default=False,
        help_text="Whether these values came from parameter suggestion.",
    )

    class Meta:
        abstract = True


class SurfaceGraphDriftSearchConfig(BaseSurfaceGraphDriftSearchConfig):
    surface_knowledge = models.OneToOneField(
        SurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_drift_search_config",
        help_text="SurfaceKnowledge entry this GraphRAG drift search configuration applies to.",
    )


class InlineSurface(TimestampMixin, models.Model):
    task_node = models.OneToOneField(
        "tables.TaskNode",
        on_delete=models.CASCADE,
        related_name="inline_surface",
        help_text="TaskNode that owns this ad-hoc surface. Deleted with the node.",
    )
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Free-form text appended to the agent prompt when this surface is active. Empty string means no extra instructions.",
    )

    class Meta(TimestampMixin.Meta):
        pass


class InlineSurfacePythonTool(BaseSurfacePythonTool):
    inline_surface = models.ForeignKey(
        InlineSurface,
        on_delete=models.CASCADE,
        related_name="python_tools",
        help_text="InlineSurface this entry belongs to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inline_surface", "python_tool"],
                name="uniq_inline_surface_python_tool",
            ),
        ]


class InlineSurfaceMcpTool(BaseSurfaceMcpTool):
    inline_surface = models.ForeignKey(
        InlineSurface,
        on_delete=models.CASCADE,
        related_name="mcp_tools",
        help_text="InlineSurface this entry belongs to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inline_surface", "mcp_tool"],
                name="uniq_inline_surface_mcp_tool",
            ),
        ]


class InlineSurfaceStorageItem(BaseSurfaceStorageItem):
    inline_surface = models.ForeignKey(
        InlineSurface,
        on_delete=models.CASCADE,
        related_name="storage_items",
        help_text="InlineSurface this storage permission entry belongs to.",
    )
    storage_file = models.ForeignKey(
        "tables.StorageFile",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="StorageFile whose access is being configured for this surface.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inline_surface", "storage_file"],
                name="uniq_inline_surface_storage_item",
            ),
        ]


class InlineSurfaceKnowledge(BaseSurfaceKnowledge):
    inline_surface = models.ForeignKey(
        InlineSurface,
        on_delete=models.CASCADE,
        related_name="knowledge",
        help_text="InlineSurface this knowledge collection is attached to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["inline_surface", "collection"],
                name="uniq_inline_surface_knowledge",
            ),
        ]


class InlineSurfaceNaiveSearchConfig(BaseSurfaceNaiveSearchConfig):
    surface_knowledge = models.OneToOneField(
        InlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="naive_search_config",
        help_text="InlineSurfaceKnowledge entry this naive search configuration applies to.",
    )


class InlineSurfaceGraphBasicSearchConfig(BaseSurfaceGraphBasicSearchConfig):
    surface_knowledge = models.OneToOneField(
        InlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_basic_search_config",
        help_text="InlineSurfaceKnowledge entry this GraphRAG basic search configuration applies to.",
    )


class InlineSurfaceGraphLocalSearchConfig(BaseSurfaceGraphLocalSearchConfig):
    surface_knowledge = models.OneToOneField(
        InlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_local_search_config",
        help_text="InlineSurfaceKnowledge entry this GraphRAG local search configuration applies to.",
    )


class InlineSurfaceGraphGlobalSearchConfig(BaseSurfaceGraphGlobalSearchConfig):
    surface_knowledge = models.OneToOneField(
        InlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_global_search_config",
        help_text="InlineSurfaceKnowledge entry this GraphRAG global search configuration applies to.",
    )


class InlineSurfaceGraphDriftSearchConfig(BaseSurfaceGraphDriftSearchConfig):
    surface_knowledge = models.OneToOneField(
        InlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_drift_search_config",
        help_text="InlineSurfaceKnowledge entry this GraphRAG drift search configuration applies to.",
    )


class AgentInlineSurface(TimestampMixin, models.Model):
    agent_node = models.OneToOneField(
        "tables.AgentNode",
        on_delete=models.CASCADE,
        related_name="inline_surface",
        help_text="AgentNode that owns this ad-hoc surface. Deleted with the node.",
    )
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Free-form text appended to the agent prompt when this surface is active. Empty string means no extra instructions.",
    )

    class Meta(TimestampMixin.Meta):
        pass


class AgentInlineSurfacePythonTool(BaseSurfacePythonTool):
    agent_inline_surface = models.ForeignKey(
        AgentInlineSurface,
        on_delete=models.CASCADE,
        related_name="python_tools",
        help_text="AgentInlineSurface this entry belongs to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent_inline_surface", "python_tool"],
                name="uniq_agent_inline_surface_python_tool",
            ),
        ]


class AgentInlineSurfaceMcpTool(BaseSurfaceMcpTool):
    agent_inline_surface = models.ForeignKey(
        AgentInlineSurface,
        on_delete=models.CASCADE,
        related_name="mcp_tools",
        help_text="AgentInlineSurface this entry belongs to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent_inline_surface", "mcp_tool"],
                name="uniq_agent_inline_surface_mcp_tool",
            ),
        ]


class AgentInlineSurfaceStorageItem(BaseSurfaceStorageItem):
    agent_inline_surface = models.ForeignKey(
        AgentInlineSurface,
        on_delete=models.CASCADE,
        related_name="storage_items",
        help_text="AgentInlineSurface this storage permission entry belongs to.",
    )
    storage_file = models.ForeignKey(
        "tables.StorageFile",
        on_delete=models.CASCADE,
        related_name="+",
        help_text="StorageFile whose access is being configured for this surface.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent_inline_surface", "storage_file"],
                name="uniq_agent_inline_surface_storage_item",
            ),
        ]


class AgentInlineSurfaceKnowledge(BaseSurfaceKnowledge):
    agent_inline_surface = models.ForeignKey(
        AgentInlineSurface,
        on_delete=models.CASCADE,
        related_name="knowledge",
        help_text="AgentInlineSurface this knowledge collection is attached to.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["agent_inline_surface", "collection"],
                name="uniq_agent_inline_surface_knowledge",
            ),
        ]


class AgentInlineSurfaceNaiveSearchConfig(BaseSurfaceNaiveSearchConfig):
    surface_knowledge = models.OneToOneField(
        AgentInlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="naive_search_config",
        help_text="AgentInlineSurfaceKnowledge entry this naive search configuration applies to.",
    )


class AgentInlineSurfaceGraphBasicSearchConfig(BaseSurfaceGraphBasicSearchConfig):
    surface_knowledge = models.OneToOneField(
        AgentInlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_basic_search_config",
        help_text="AgentInlineSurfaceKnowledge entry this GraphRAG basic search configuration applies to.",
    )


class AgentInlineSurfaceGraphLocalSearchConfig(BaseSurfaceGraphLocalSearchConfig):
    surface_knowledge = models.OneToOneField(
        AgentInlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_local_search_config",
        help_text="AgentInlineSurfaceKnowledge entry this GraphRAG local search configuration applies to.",
    )


class AgentInlineSurfaceGraphGlobalSearchConfig(BaseSurfaceGraphGlobalSearchConfig):
    surface_knowledge = models.OneToOneField(
        AgentInlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_global_search_config",
        help_text="AgentInlineSurfaceKnowledge entry this GraphRAG global search configuration applies to.",
    )


class AgentInlineSurfaceGraphDriftSearchConfig(BaseSurfaceGraphDriftSearchConfig):
    surface_knowledge = models.OneToOneField(
        AgentInlineSurfaceKnowledge,
        on_delete=models.CASCADE,
        related_name="graph_drift_search_config",
        help_text="AgentInlineSurfaceKnowledge entry this GraphRAG drift search configuration applies to.",
    )
