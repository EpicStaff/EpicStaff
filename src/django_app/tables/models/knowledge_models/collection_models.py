import ntpath

from django.core.exceptions import SuspiciousFileOperation
from django.db import models

from loguru import logger

from tables.models.base_models import ActiveManager, SoftDeleteFields, SoftDeleteMixin
from tables.models.rbac_models.org_scoped import OrgScopedModel


def _is_bare_file_name(file_name: str) -> bool:
    """
    True when file_name is a plain file name carrying no path component.

    Anything that could steer a directory join away from its target folder is
    not a name we accept: directory separators (both flavours, since the
    consumer may run on either platform), a Windows drive prefix, and the
    current/parent directory entries.
    """
    if file_name in (".", ".."):
        return False
    if ntpath.splitdrive(file_name)[0]:
        return False
    return "/" not in file_name and "\\" not in file_name


class SourceCollection(OrgScopedModel, SoftDeleteMixin, models.Model):
    objects = ActiveManager()
    all_objects = models.Manager()

    class SourceCollectionStatus(models.TextChoices):
        """
        Status of SourceCollection
        """

        EMPTY = "empty"
        UPLOADING = "uploading"
        COMPLETED = "completed"
        WARNING = "warning"

    class SourceCollectionOrigin(models.TextChoices):
        """
        Origin of SourceCollection
        """

        USER = "user"
        NODE = "node"
        TOOL = "tool"

    collection_id = models.AutoField(primary_key=True)
    collection_name = models.CharField(max_length=255, blank=True)
    description = models.TextField(
        blank=True,
        default="",
        help_text=(
            "LLM-facing context describing this collection's contents. Appended to "
            "the description of every knowledge tool generated for this collection "
            "so agents know when to use it. Blank means no extra context is added."
        ),
    )
    collection_origin = models.CharField(
        max_length=20,
        choices=SourceCollectionOrigin.choices,
        default=SourceCollectionOrigin.USER,
    )

    # TODO: change to OneToMany relation with User model after implementation auth
    user_id = models.CharField(max_length=120, default="dummy_user", blank=True)
    status = models.CharField(
        max_length=20,
        choices=SourceCollectionStatus.choices,
        default=SourceCollectionStatus.EMPTY,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta(OrgScopedModel.Meta):
        constraints = [
            models.UniqueConstraint(
                fields=["org", "collection_name"],
                condition=models.Q(is_soft_deleted=False),
                name="unique_collection_name_per_org",
            )
        ]

    def __str__(self):
        return self.collection_name

    def _generate_unique_collection_name(self, base_name):
        existing_names = SourceCollection.objects.filter(
            org_id=self.org_id, collection_name__startswith=base_name
        ).values_list("collection_name", flat=True)

        if base_name not in existing_names:
            return base_name

        counter = 1
        while True:
            new_name = f"{base_name} ({counter})"
            if new_name not in existing_names:
                return new_name
            counter += 1

    def save(self, *args, **kwargs):
        base_name = self.collection_name or "Untitled Collection"

        if (
            not self.pk
            or self.__class__.objects.filter(pk=self.pk)
            .values_list("collection_name", flat=True)
            .first()
            != base_name
        ):
            self.collection_name = self._generate_unique_collection_name(base_name)

        super().save(*args, **kwargs)

    def update_collection_status(self):
        """Update collection status based on document statuses"""
        if not self.documents.exists():
            self.status = self.SourceCollectionStatus.EMPTY
        else:
            # TODO: implement status aggregation logic
            pass
        self.save(update_fields=["status", "updated_at"])


class DocumentContent(models.Model):
    """
    Binary storage for file contents.
    """

    content = models.BinaryField(help_text="Binary file content (max 12MB)")

    def __str__(self):
        return f"Content {self.content_id}"


class DocumentMetadata(SoftDeleteFields, models.Model):
    """
    Model to store file metadata records
    """

    class DocumentFileType(models.TextChoices):
        PDF = "pdf"
        CSV = "csv"
        DOCX = "docx"
        TXT = "txt"
        JSON = "json"
        HTML = "html"
        MD = "md"

    document_id = models.AutoField(primary_key=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_type = models.CharField(
        max_length=10, choices=DocumentFileType.choices, blank=True
    )
    file_size = models.PositiveIntegerField(help_text="Size in bytes", null=True)

    source_collection = models.ForeignKey(
        SourceCollection,
        on_delete=models.CASCADE,
        related_name="documents",
        null=True,
    )
    document_content = models.ForeignKey(
        DocumentContent,
        on_delete=models.CASCADE,
        related_name="metadata_records",
        null=True,
    )

    class Meta:
        indexes = [models.Index(fields=["source_collection"])]

    def save(self, *args, **kwargs):
        if self.file_name and not _is_bare_file_name(self.file_name):
            raise SuspiciousFileOperation(
                f"file_name {self.file_name!r} must be a plain file name, not a path"
            )

        res = super().save(*args, **kwargs)
        collection = self.source_collection
        if collection is None:
            logger.warning(
                f"Source collection for document {self.file_name} not found!"
            )
        else:
            self.source_collection.update_collection_status()
        return res

    def delete(self, using=None, keep_parents=None):
        res = super().delete(using, keep_parents)
        if self.source_collection is None:
            logger.warning(
                f"Source collection for document {self.file_name} not found!"
            )
        else:
            self.source_collection.update_collection_status()

        return res

    def __str__(self):
        return f"{self.file_name}"


class BaseRagType(SoftDeleteFields, models.Model):
    """
    Purpose: Common interface for all RAG implementations

    Relationships:
    - Belongs to one SourceCollection
    - Subclassed by concrete rag types (NaiveRAG, GraphRAG, etc.)
    """

    class RagType(models.TextChoices):
        NAIVE = "naive"
        GRAPH = "graph"

    rag_type_id = models.AutoField(primary_key=True)
    rag_type = models.CharField(max_length=30, choices=RagType.choices)

    source_collection = models.ForeignKey(
        SourceCollection,
        on_delete=models.CASCADE,
        related_name="rag_types",
    )

    class Meta:
        abstract = False  # This is a concrete model for polymorphism

    def __str__(self):
        return f"{self.rag_type}"
