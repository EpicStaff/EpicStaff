from django.db import models
from django.utils import timezone
import uuid

from pgvector.django import VectorField

from src.shared.models.knowledge_status import (
    CHUNK_PARAM_FIELDS,
    RACE_GUARD_IN_PROGRESS,
    compute_rag_status,
    summarize_rag_error,
    is_snapshot_current,
    format_error_message,
)
from ..embedding_models import EmbeddingConfig
from .collection_models import BaseRagType, DocumentMetadata
from ..crew_models import Agent


class NaiveRag(models.Model):
    class NaiveRagStatus(models.TextChoices):
        """Aggregate status of a NaiveRag, rolled up from per-document statuses."""

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
        """Recompute aggregate status from per-document statuses via the shared
        single-source rule (see src.shared.models.knowledge_status). Stamps
        indexed_at when the RAG reaches COMPLETED.

        Persists via self.save() — must be called inside or after @transaction.atomic
        so the status update is visible atomically to polling clients.
        """
        doc_statuses = list(self.naive_rag_configs.values_list("status", flat=True))
        self.rag_status = compute_rag_status(doc_statuses)
        self.error_message = summarize_rag_error(doc_statuses)
        update_fields = ["rag_status", "error_message", "updated_at"]
        if self.rag_status == self.NaiveRagStatus.COMPLETED:
            self.indexed_at = timezone.now()
            update_fields.append("indexed_at")
        self.save(update_fields=update_fields)


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
        CHUNKED = "chunked"  # Preview chunks created, no active worker
        INDEXING = "indexing"
        COMPLETED = "completed"  # Indexed chunks + embeddings created
        WARNING = "warning"
        FAILED = "failed"

    class DocumentErrorCode(models.TextChoices):
        """Categorized indexing error codes persisted on a document config."""

        CHUNKING_FAILED = "chunking_failed"
        EMBEDDING_FAILED = "embedding_failed"
        EMBEDDER_AUTH = "embedder_auth"
        EMBEDDER_RATE_LIMIT = "embedder_rate_limit"
        UNKNOWN = "unknown"
        NONE = "none"

    # Statuses that indicate an active worker is running on this document.
    # Used by apply_param_updates() to skip status realignment while indexing.
    # NOTE: CHUNKED is intentionally excluded — see RACE_GUARD_IN_PROGRESS in
    # src.shared.models.knowledge_status for the full explanation.
    IN_PROGRESS_STATUSES = RACE_GUARD_IN_PROGRESS

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

    error_message = models.TextField(null=True, blank=True)
    error_code = models.CharField(
        max_length=32,
        choices=DocumentErrorCode.choices,
        default=DocumentErrorCode.NONE,
    )
    failed_at = models.DateTimeField(null=True, blank=True)

    # Snapshot of chunk params at the time of last successful indexing.
    # Compared against the live params to decide whether re-indexing is needed.
    indexed_chunk_strategy = models.CharField(
        max_length=20,
        choices=ChunkStrategy.choices,
        null=True,
        blank=True,
    )
    indexed_chunk_size = models.PositiveIntegerField(null=True, blank=True)
    indexed_chunk_overlap = models.PositiveIntegerField(null=True, blank=True)
    indexed_additional_params = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    @property
    def total_chunks(self):
        return self.chunks.count()

    @property
    def total_embeddings(self):
        return self.embeddings.count()

    def is_snapshot_current(self) -> bool:
        """True iff the indexed_chunk_* snapshot matches the current live params."""
        live = {f: getattr(self, f) for f in CHUNK_PARAM_FIELDS}
        indexed = {f: getattr(self, f"indexed_{f}") for f in CHUNK_PARAM_FIELDS}
        return is_snapshot_current(live, indexed)

    def _clear_error(self) -> None:
        self.error_message = None
        self.error_code = self.DocumentErrorCode.NONE
        self.failed_at = None

    def apply_param_updates(self, updates: dict) -> bool:
        """Mutate chunk-param fields in place (in-memory only). If anything
        changed and no worker is running, realign status to COMPLETED/NEW.
        Returns True iff changed; the service then persists + drops the preview."""
        changed = any(
            f in updates and updates[f] != getattr(self, f) for f in CHUNK_PARAM_FIELDS
        )
        if not changed:
            return False
        for f, v in updates.items():
            setattr(self, f, v)

        if self.status not in self.IN_PROGRESS_STATUSES:
            Status = self.NaiveRagDocumentStatus
            self.status = Status.COMPLETED if self.is_snapshot_current() else Status.NEW
            self._clear_error()

        return True

    def start_attempt(self, new_status) -> None:
        """Flip status and clear stale error in memory (the caller persists)."""
        self.status = new_status
        self._clear_error()

    def mark_completed(self, processed_at=None) -> None:
        """Flip status to COMPLETED and clear any stale error in memory (caller persists)."""
        self.status = self.NaiveRagDocumentStatus.COMPLETED
        self._clear_error()
        self.processed_at = processed_at

    def mark_failed(self, error_code, exc: BaseException) -> str:
        """Set FAILED + code + truncated message + timestamp in memory and
        return the message (the caller persists)."""
        message = format_error_message(exc)
        self.status = self.NaiveRagDocumentStatus.FAILED
        self.error_code = error_code
        self.error_message = message
        self.failed_at = timezone.now()
        return message

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
