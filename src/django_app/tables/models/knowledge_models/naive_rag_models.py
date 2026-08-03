import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import PositiveIntegerField
from pgvector.django import VectorField

from ..crew_models import Agent
from ..embedding_models import EmbeddingConfig
from .collection_models import BaseRagType, DocumentMetadata


class NaiveRag(models.Model):
    class NaiveRagStatus(models.TextChoices):
        """
        - NEW - new rag
        - PROCESSING - rag is in indexing.
        - COMPLETED - rag is indexed.
        - FAILED - rag failed at indexing.
        - PARTIAL - rag is completed and has completed and failed documents.
        - OUTDATED - rag completed, but outdated by changes of indexing config, embedding config
         or document content.
        """

        NEW = "new"
        PROCESSING = "processing"
        COMPLETED = "completed"
        WARNING = "warning"  # deprecated
        FAILED = "failed"
        PARTIAL = "partial"
        OUTDATED = "outdated"

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
    outdated_reasons = models.JSONField(default=dict, blank=True)

    indexing_document_config_ids = ArrayField(
        base_field=PositiveIntegerField(),
        default=list,
        blank=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    def add_outdated_reason(self, code: str, detail: str):
        self.outdated_reasons.setdefault(code, detail)

    def clear_outdated_reason(self):
        self.outdated_reasons.clear()

    def update_rag_status(self) -> bool:
        config_statuses = set(self.naive_rag_configs.values_list("status", flat=True).distinct())
        config_status_enum = NaiveRagDocumentConfig.NaiveRagDocumentStatus

        if config_status_enum.OUTDATED in config_statuses or self.outdated_reasons:
            new_status = self.NaiveRagStatus.OUTDATED
        elif config_status_enum.PROCESSING in config_statuses:
            new_status = self.NaiveRagStatus.PROCESSING
        elif config_statuses.issuperset([config_status_enum.COMPLETED, config_status_enum.FAILED]):
            new_status = self.NaiveRagStatus.PARTIAL
        elif config_status_enum.COMPLETED in config_statuses:
            new_status = self.NaiveRagStatus.COMPLETED
        elif config_status_enum.FAILED in config_statuses:
            new_status = self.NaiveRagStatus.FAILED
        else:
            new_status = self.NaiveRagStatus.NEW

        if self.rag_status != new_status:
            self.rag_status = new_status
            return True
        return False


class NaiveRagDocumentConfig(models.Model):
    """
    Document-level RAG type with per-document parameters.

    Scope: Per-document processing

    Relationships:
    - Belongs to one DocumentMetadata
    - Has many NaiveRAGChunk (chunks from this document)
    - Has many NaiveRAGEmbedding (embeddings from this document)
    """

    class DocumentErrorCode(models.TextChoices):
        CHUNKING_FAILED = "chunking_failed"
        NO_CHUNKS_PRODUCED = "no_chunks_produced"
        EMBEDDING_FAILED = "embedding_failed"
        EMBEDDER_AUTH = "embedder_auth"
        EMBEDDER_RATE_LIMIT = "embedder_rate_limit"
        UNKNOWN = "unknown"
        NONE = "none"

    class ChunkStrategy(models.TextChoices):
        TOKEN = "token"
        CHARACTER = "character"
        MARKDOWN = "markdown"
        JSON = "json"
        HTML = "html"
        CSV = "csv"

    class NaiveRagDocumentStatus(models.TextChoices):
        """
        - NEW - new document config.
        - PROCESSING - document config is in indexing.
        - COMPLETED - document config is indexed.
        - FAILED - document config failed at indexing
        - OUTDATED - document config completed, but outdated by changes of indexing config,
        embedding config or document content.
        """

        NEW = "new"
        PROCESSING = "processing"
        CHUNKING = "chunking"  # deprecated
        CHUNKED = "chunked"  # deprecated
        INDEXING = "indexing"  # deprecated
        COMPLETED = "completed"
        WARNING = "warning"  # deprecated
        FAILED = "failed"
        OUTDATED = "outdated"

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
    outdated_reasons = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(
        max_length=32, choices=DocumentErrorCode.choices, default=DocumentErrorCode.NONE
    )
    error_message = models.TextField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)

    indexed_chunk_strategy = models.CharField(
        max_length=20, choices=ChunkStrategy.choices, null=True, blank=True
    )

    indexed_chunk_size = models.PositiveIntegerField(null=True, blank=True)
    indexed_chunk_overlap = models.PositiveIntegerField(null=True, blank=True)
    indexed_additional_params = models.JSONField(null=True, blank=True)

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

    def add_outdated_reason(self, code: str, detail: str):
        self.outdated_reasons.setdefault(code, detail)


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
