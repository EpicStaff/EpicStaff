from django.db import models
import uuid

from pgvector.django import VectorField


from ..embedding_models import EmbeddingConfig
from .collection_models import BaseRagType, DocumentMetadata
from ..crew_models import Agent


class NaiveRag(models.Model):
    class NaiveRagStatus(models.TextChoices):
        """
        Status of document in SourceCollection
        """

        NEW = "new"
        PROCESSING = "processing"
        COMPLETED = "completed"
        WARNING = "warning"
        FAILED = "failed"

    naive_rag_id = models.AutoField(primary_key=True)
    base_rag_type = models.ForeignKey(
        BaseRagType,
        on_delete=models.CASCADE,
        related_name="naive_rags",
        limit_choices_to={"rag_type": BaseRagType.RagType.NAIVE},
    )
    embedder = models.ForeignKey(
        EmbeddingConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    agents = models.ManyToManyField(
        "Agent",
        through="AgentNaiveRag",
        related_name="naive_rags",  # Access from Agent: agent.naive_rags.all()
        blank=True,
        help_text="Agents that have access to this NaiveRag",
    )
    rag_status = models.CharField(
        max_length=20,
        choices=NaiveRagStatus.choices,
        default=NaiveRagStatus.NEW,
    )
    error_message = models.TextField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    def update_rag_status(self: "NaiveRag"):
        naive_rag_document_statuses = set(
            self.naive_rag_configs.values_list("status", flat=True)
        )

        NEW = NaiveRag.NaiveRagStatus.NEW
        PROCESSING = NaiveRag.NaiveRagStatus.PROCESSING
        WARNING = NaiveRag.NaiveRagStatus.WARNING
        FAILED = NaiveRag.NaiveRagStatus.FAILED
        COMPLETED = NaiveRag.NaiveRagStatus.COMPLETED

        if not naive_rag_document_statuses or naive_rag_document_statuses == {NEW}:
            current_status = NEW
        elif naive_rag_document_statuses == {COMPLETED}:
            current_status = COMPLETED
        elif naive_rag_document_statuses == {FAILED}:
            current_status = FAILED
        elif PROCESSING in naive_rag_document_statuses:
            current_status = PROCESSING
        elif (
            FAILED in naive_rag_document_statuses
            or WARNING in naive_rag_document_statuses
        ):
            current_status = WARNING
        else:
            current_status = WARNING

        self.status = current_status
        self.save()


class NaiveRagDocumentConfig(models.Model):
    """
    Document-level RAG type with per-document parameters.

    Scope: Per-document processing

    Relationships:
    - Belongs to one DocumentMetadata
    - Has many NaiveRAGChunk (chunks from this document)
    - Has many NaiveRAGEmbedding (embeddings from this document)
    """

    class ChunkStrategy(models.TextChoices):
        TOKEN = "token"
        CHARACTER = "character"
        MARKDOWN = "markdown"
        JSON = "json"
        HTML = "html"
        CSV = "csv"

    class NaiveRagDocumentStatus(models.TextChoices):
        """
        Status flow: new → chunking → chunked → indexing → completed
        Error states: failed, warning (can occur at any step)
        """

        NEW = "new"
        CHUNKING = "chunking"
        CHUNKED = "chunked"  # Preview chunks created
        INDEXING = "indexing"
        COMPLETED = "completed"  # Indexed chunks created
        WARNING = "warning"
        FAILED = "failed"

    naive_rag_document_id = models.AutoField(primary_key=True)

    naive_rag = models.ForeignKey(
        NaiveRag, on_delete=models.CASCADE, related_name="naive_rag_configs"
    )

    document = models.ForeignKey(
        DocumentMetadata,
        on_delete=models.CASCADE,
        related_name="naive_rag_document_config",
    )

    chunk_strategy = models.CharField(
        max_length=20,
        choices=ChunkStrategy.choices,
        default=ChunkStrategy.TOKEN,
    )
    chunk_size = models.PositiveIntegerField(
        default=1000, help_text="Size of each chunk (tokens or characters)"
    )
    chunk_overlap = models.PositiveIntegerField(
        default=150, help_text="Overlap between consecutive chunks"
    )

    additional_params = models.JSONField(
        default=dict, help_text="Strategy-specific params (e.g., separators, headers)"
    )

    status = models.CharField(
        max_length=20,
        choices=NaiveRagDocumentStatus.choices,
        default=NaiveRagDocumentStatus.NEW,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    @property
    def total_chunks(self):
        return self.chunks.count()

    @property
    def total_embeddings(self):
        return self.embeddings.count()

    class Meta:
        indexes = [
            models.Index(fields=["naive_rag", "status"]),
            models.Index(fields=["document"]),
        ]
        # support only one configuration of document per one naive rag implementation
        # (could be many implementations per collection)
        constraints = [
            models.UniqueConstraint(
                fields=["naive_rag", "document"],
                name="unique_document_per_naive_rag",
            )
        ]

    def __str__(self):
        return f"NaiveRAG: {self.document.file_name}"


class NaiveRagChunk(models.Model):
    """
    Text chunks generated by NaiveRAG strategy.
    """

    chunk_id = models.AutoField(primary_key=True)

    naive_rag_document_config = models.ForeignKey(
        NaiveRagDocumentConfig,
        on_delete=models.CASCADE,
        related_name="chunks",
    )

    text = models.TextField()
    chunk_index = models.PositiveIntegerField(
        help_text="Order of this chunk in the document"
    )

    token_count = models.PositiveIntegerField(null=True, blank=True)
    overlap_start_index = models.PositiveIntegerField(null=True, blank=True)
    overlap_end_index = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(
        default=dict, help_text="Chunk-specific metadata (page numbers, sections, etc.)"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["chunk_index"]
        indexes = [
            models.Index(fields=["naive_rag_document_config", "chunk_index"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["naive_rag_document_config", "chunk_index"],
                name="unique_chunk_index_per_naive_rag_document_config",
            )
        ]

    def __str__(self):
        return f"Chunk {self.chunk_index} of {self.naive_rag_document_config.document.file_name}"


class NaiveRagEmbedding(models.Model):
    """
    Vector embeddings for NaiveRAG chunks.
    """

    embedding_id = models.UUIDField(
        primary_key=True, default=uuid.uuid4, editable=False
    )

    naive_rag_document_config = models.ForeignKey(
        NaiveRagDocumentConfig,
        on_delete=models.CASCADE,
        related_name="embeddings",
    )
    chunk = models.OneToOneField(
        NaiveRagChunk,
        on_delete=models.CASCADE,
        related_name="embedding",
    )

    vector = VectorField(
        dimensions=None,  # Flexible dimensions based on embedder
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["naive_rag_document_config"])]

    def __str__(self):
        return f"Embedding for {self.chunk}"


class AgentNaiveRag(models.Model):
    """
    Link table connecting Agents to NaiveRag implementations.

    Purpose:
    - Enables ManyToMany relationship without modifying Agent model
    - Allows adding future RAG types (GraphRag, HybridRag) independently
    - Could stores relationship metadata (priority, is_active)

    Current Restriction:
    - agent field has unique=True: temporarily enforces ONE NaiveRag per Agent
    - Remove unique=True later to allow multiple NaiveRags per Agent

    Design Pattern:
    - Relationship defined on NaiveRag model, not Agent
    - Agent accesses via reverse relation: agent.naive_rags.all()
    - Keeps Agent model clean and unchanged when adding new RAG types
    """

    agent = models.ForeignKey(
        Agent,
        on_delete=models.CASCADE,
        unique=True,  # TEMPORARY: Remove to allow multiple NaiveRags per Agent
        related_name="agent_naive_rags",
    )
    naive_rag = models.ForeignKey(
        NaiveRag, on_delete=models.CASCADE, related_name="agent_links"
    )

    @classmethod
    def check(cls, **kwargs):
        """
        Suppress W342 warning about ForeignKey(unique=True).
        This is intentional: currently 1-to-1, future Many-to-Many.
        """
        errors = super().check(**kwargs)
        return [error for error in errors if error.id != "fields.W342"]


class NaiveRagSearchConfig(models.Model):
    agent = models.OneToOneField(
        "Agent",
        on_delete=models.CASCADE,
        related_name="naive_search_config",  # Access via: agent.naive_search_config
        help_text="Agent this search configuration belongs to",
    )

    search_limit = models.PositiveIntegerField(
        default=3, blank=True, help_text="Integer between 0 and 1000 for knowledge"
    )
    similarity_threshold = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=0.2,
        blank=True,
        help_text="Float between 0.00 and 1.00 for knowledge",
    )


class NaiveRagPreviewChunk(models.Model):
    """
    Temporary preview chunks for testing different chunking parameters.

    Purpose:
    - Allow users to preview chunks before committing to indexing
    - Support iterative chunking parameter tuning

    Lifecycle:
    - Created when user triggers process-chunking endpoint
    - Deleted when:
      1. New chunking request arrives (replaced with new preview chunks)
      2. Document is successfully indexed (no longer needed)
    """

    preview_chunk_id = models.AutoField(primary_key=True)

    naive_rag_document_config = models.ForeignKey(
        NaiveRagDocumentConfig,
        on_delete=models.CASCADE,
        related_name="preview_chunks",
    )

    text = models.TextField()
    chunk_index = models.PositiveIntegerField(
        help_text="Order of this chunk in the document"
    )

    token_count = models.PositiveIntegerField(null=True, blank=True)
    overlap_start_index = models.PositiveIntegerField(null=True, blank=True)
    overlap_end_index = models.PositiveIntegerField(null=True, blank=True)
    metadata = models.JSONField(
        default=dict,
        help_text="Chunk-specific metadata (page numbers, sections, etc.)",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["chunk_index"]
        indexes = [
            models.Index(fields=["naive_rag_document_config", "chunk_index"]),
        ]

    def __str__(self):
        return f"PreviewChunk {self.chunk_index} of {self.naive_rag_document_config.document.file_name}"
