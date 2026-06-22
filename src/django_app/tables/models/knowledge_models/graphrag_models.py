from django.db import models
from ..crew_models import Task


from ..embedding_models import EmbeddingConfig
from ..llm_models import LLMConfig
from .collection_models import BaseRagType, DocumentMetadata
from ..crew_models import Agent


class GraphRag(models.Model):
    class GraphRagStatus(models.TextChoices):
        """Status of GraphRag."""

        NEW = "new"
        PROCESSING = "processing"
        COMPLETED = "completed"
        WARNING = "warning"
        FAILED = "failed"

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
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "graph_rag"


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
