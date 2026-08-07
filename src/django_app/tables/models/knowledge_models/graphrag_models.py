from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import PositiveIntegerField

from ..embedding_models import EmbeddingConfig
from ..llm_models import LLMConfig
from .collection_models import BaseRagType, DocumentMetadata
from ..crew_models import Agent


class GraphRag(models.Model):
    class GraphRagStatus(models.TextChoices):
        """
        - NEW - new rag
        - PROCESSING - rag is in indexing
        - COMPLETED - rag is indexed
        - FAILED - rag failed at indexing
        - OUTDATED - rag completed, but outdated by changes of indexing config, embedding config
        or document content.
        """

        NEW = "new"
        PROCESSING = "processing"
        COMPLETED = "completed"
        WARNING = "warning"  # deprecated
        FAILED = "failed"
        CANCELLED = "cancelled"
        OUTDATED = "outdated"

    graph_rag_id = models.AutoField(primary_key=True)
    base_rag_type = models.ForeignKey(
        BaseRagType,
        on_delete=models.CASCADE,
        related_name="graph_rags",
        limit_choices_to={"rag_type": BaseRagType.RagType.GRAPH},
    )
    embedder = models.ForeignKey(
        EmbeddingConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    llm = models.ForeignKey(
        LLMConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    index_config = models.OneToOneField(
        "GraphRagIndexConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="graph_rag",
        help_text="Index configuration for this GraphRag",
    )

    agents = models.ManyToManyField(
        Agent,
        through="AgentGraphRag",
        related_name="graph_rags",
        blank=True,
        help_text="Agents that have access to this GraphRag",
    )
    rag_status = models.CharField(
        max_length=20,
        choices=GraphRagStatus.choices,
        default=GraphRagStatus.NEW,
    )
    outdated_reasons = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(null=True, blank=True)

    indexing_document_config_ids = ArrayField(
        base_field=PositiveIntegerField(),
        default=list,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "graph_rag"

    def add_outdated_reason(self, code: str, detail: str):
        self.outdated_reasons.setdefault(code, detail)

    def clear_outdated_reason(self):
        self.outdated_reasons.clear()

    def update_rag_status(self: "GraphRag"):
        """Update status based on document states."""
        document_statuses = set(
            self.graph_rag_documents.values_list("status", flat=True).distinct()
        )

        if (
            GraphRagDocument.Status.OUTDATED in document_statuses
            or self.outdated_reasons
        ):
            new_status = self.GraphRagStatus.OUTDATED
        elif self.indexing_document_config_ids:
            new_status = self.GraphRagStatus.PROCESSING
        elif GraphRagDocument.Status.COMPLETED in document_statuses:
            new_status = self.GraphRagStatus.COMPLETED
        elif GraphRagDocument.Status.FAILED in document_statuses:
            new_status = self.GraphRagStatus.FAILED
        else:
            new_status = self.GraphRagStatus.NEW

        if self.rag_status != new_status:
            self.rag_status = new_status
            return True
        return False


class AgentGraphRag(models.Model):
    """
    Link table connecting Agents to GraphRag implementations.

    Purpose:
    - Enables ManyToMany relationship without modifying Agent model
    - Allows adding future RAG types (HybridRag, etc) independently

    Current Restriction:
    - agent field has unique=True: temporarily enforces ONE GraphRag per Agent
    - Remove unique=True later to allow multiple GraphRag per Agent

    Design Pattern:
    - Relationship defined on GraphRag model, not Agent
    - Agent accesses via reverse relation: agent.graph_rags.all()
    - Keeps Agent model clean and unchanged when adding new RAG types
    """

    class SearchMethod(models.TextChoices):
        BASIC = "basic", "Basic Search"
        LOCAL = "local", "Local Search"
        GLOBAL = "global", "Global Search"
        DRIFT = "drift", "Drift Search"

    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        unique=True,  # TEMPORARY: Remove to allow multiple GraphRag per Agent
        related_name="agent_graph_rags",
    )
    graph_rag = models.ForeignKey(
        GraphRag, on_delete=models.CASCADE, related_name="agent_links"
    )
    search_method = models.CharField(
        max_length=10,
        choices=SearchMethod.choices,
        default=SearchMethod.BASIC,
        help_text="Active search method: basic or local",
    )

    class Meta:
        db_table = "agent_graph_rag"

    @classmethod
    def check(cls, **kwargs):
        """
        Suppress W342 warning about ForeignKey(unique=True).
        This is intentional: currently 1-to-1, future Many-to-Many.
        """
        errors = super().check(**kwargs)
        return [error for error in errors if error.id != "fields.W342"]


class GraphRagDocument(models.Model):
    """
    Link table connecting GraphRag to specific documents.

    Purpose:
    - GraphRag can include a subset of documents from the collection
    - Allows adding/removing documents from GraphRag independently
    """

    class Status(models.TextChoices):
        """
        - NEW - new document link
        - COMPLETED - document is indexed
        - FAILED - document failed at indexing
        - OUTDATED - document is outdated, but outdated by changes of indexing config, embedding
        config or document content.
        """

        NEW = "new"
        COMPLETED = "completed"
        FAILED = "failed"
        OUTDATED = "outdated"

    graph_rag_document_id = models.AutoField(primary_key=True)
    graph_rag = models.ForeignKey(
        GraphRag,
        on_delete=models.CASCADE,
        related_name="graph_rag_documents",
    )
    document = models.ForeignKey(
        DocumentMetadata,
        on_delete=models.CASCADE,
        related_name="graph_rag_links",
    )
    status = models.CharField(
        default=Status.NEW,
        choices=Status.choices,
        max_length=20,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "graph_rag_document"
        constraints = [
            models.UniqueConstraint(
                fields=["graph_rag", "document"],
                name="unique_graph_rag_document",
            )
        ]

    def __str__(self):
        return f"GraphRagDocument({self.graph_rag_id}, {self.document_id})"


class GraphRagInputFileType(models.TextChoices):
    CSV = "csv", "CSV"
    TEXT = "text", "Text"
    JSON = "json", "JSON"


class GraphRagChunkStrategyType(models.TextChoices):
    TOKENS = "tokens", "Tokens"
    SENTENCE = "sentence", "Sentence"


class GraphRagIndexConfig(models.Model):
    """
    Unified index configuration for GraphRAG.
    Contains all settings for input, chunking, entity extraction, and clustering.
    """

    def default_entity_types():
        """Default entity extraction types."""
        return ["organization", "person", "geo", "event"]

    # --- Input Configuration ---
    file_type = models.CharField(
        max_length=10,
        choices=GraphRagInputFileType.choices,
        default=GraphRagInputFileType.TEXT,
        help_text="Input file type to use (csv, text, json).",
    )

    # --- Chunking Configuration ---
    chunk_size = models.PositiveIntegerField(
        default=1200,
        help_text="The chunk size to use.",
    )
    chunk_overlap = models.PositiveIntegerField(
        default=100,
        help_text="The chunk overlap to use.",
    )
    chunk_strategy = models.CharField(
        max_length=20,
        choices=GraphRagChunkStrategyType.choices,
        default=GraphRagChunkStrategyType.TOKENS,
        help_text="The chunking strategy to use (tokens or sentence).",
    )

    # --- Entity Extraction Configuration ---
    entity_types = models.JSONField(
        default=default_entity_types,
        help_text=(
            "The entity extraction types to use. "
            "Defaults to ['organization', 'person', 'geo', 'event']"
        ),
    )
    max_gleanings = models.PositiveIntegerField(
        default=1,
        help_text="The maximum number of entity gleanings to use.",
    )

    # --- Cluster Graph Configuration ---
    max_cluster_size = models.PositiveIntegerField(
        default=10,
        help_text="The maximum cluster size to use.",
    )

    class Meta:
        db_table = "graph_rag_index_config"

    def __str__(self):
        return (
            f"GraphRagIndexConfig(chunk_size={self.chunk_size}, "
            f"entity_types={len(self.entity_types)}, "
            f"max_cluster_size={self.max_cluster_size})"
        )


class GraphRagBasicSearchConfig(models.Model):
    """
    The default configuration section for Basic Search.
    Linked to Agent via OneToOneField (same pattern as NaiveRagSearchConfig).
    """

    agent = models.OneToOneField(
        Agent,
        on_delete=models.CASCADE,
        related_name="graph_basic_search_config",
        help_text="Agent this basic search configuration belongs to",
    )

    prompt = models.TextField(
        null=True,
        blank=True,
        help_text="The basic search prompt to use.",
        default=None,
    )

    k = models.IntegerField(
        default=10,
        help_text="The number of text units to include in search context.",
    )

    max_context_tokens = models.IntegerField(
        default=12000,
        help_text="The maximum tokens.",
    )

    class Meta:
        db_table = "graph_rag_basic_search_config"

    def __str__(self):
        return f"GraphRagBasicSearchConfig({self.pk})"


class GraphRagLocalSearchConfig(models.Model):
    """
    The default configuration section for Local Search.
    Linked to Agent via OneToOneField (same pattern as NaiveRagSearchConfig).
    """

    agent = models.OneToOneField(
        Agent,
        on_delete=models.CASCADE,
        related_name="graph_local_search_config",
        help_text="Agent this local search configuration belongs to",
    )

    prompt = models.TextField(
        null=True,
        blank=True,
        help_text="The local search prompt to use.",
        default=None,
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

    class Meta:
        db_table = "graph_rag_local_search_config"

    def __str__(self):
        return f"GraphRagLocalSearchConfig({self.pk})"


class GraphRagGlobalSearchConfig(models.Model):
    """
    The default configuration section for Global Search.
    Linked to Agent via OneToOneField (same pattern as NaiveRagSearchConfig).

    Global Search runs a map-reduce over community reports: the map step
    answers the query against each community report batch, and the reduce
    step aggregates those partial answers into the final response.
    """

    agent = models.OneToOneField(
        Agent,
        on_delete=models.CASCADE,
        related_name="graph_global_search_config",
        help_text="Agent this global search configuration belongs to",
    )
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

    class Meta:
        db_table = "graph_rag_global_search_config"

    def __str__(self):
        return f"GraphRagGlobalSearchConfig({self.pk})"


class GraphRagDriftSearchConfig(models.Model):
    """
    The default configuration section for DRIFT Search.
    Linked to Agent via OneToOneField (same pattern as NaiveRagSearchConfig).

    DRIFT (Dynamic Reasoning and Inference with Flexible Traversal) starts
    from a primer over community reports to seed follow-up questions, then
    iteratively runs local searches to a bounded depth before a final reduce
    step. The local_search_* fields configure the local searches spawned
    during traversal.
    """

    agent = models.OneToOneField(
        Agent,
        on_delete=models.CASCADE,
        related_name="graph_drift_search_config",
        help_text="Agent this drift search configuration belongs to",
    )
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

    class Meta:
        db_table = "graph_rag_drift_search_config"

    def __str__(self):
        return f"GraphRagDriftSearchConfig({self.pk})"
