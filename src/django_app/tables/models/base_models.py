import hashlib
import json
from abc import abstractmethod
from enum import Enum
from typing import Self

from django.apps import apps
from django.db import connection, models
from django.db.models import Func, Value


class AbstractDefaultFillableModel(models.Model):
    """
    Abstract class that provides a method to fill missing fields with defaults
    from the default configuration model.
    """

    class Meta:
        abstract = True

    @abstractmethod
    def get_default_model(self) -> models.Model:
        """
        Subclasses should return the model that holds the default values.
        """
        pass

    def get_default_fields(self) -> list[str]:
        default_model = self.get_default_model()
        return {field.name for field in default_model._meta.get_fields()}

    def fill_with_defaults(self):
        """
        Fills the fields of the current model with values from the default model
        where fields are None.
        """
        # Get the default model instance
        default_model = self.get_default_model()

        # Get the field names of both the current model and the default model
        default_field_names = self.get_default_fields()
        self_field_names = {field.name for field in self._meta.get_fields()}

        # Iterate through the fields in the default model
        for field_name in default_field_names:
            # If the current field is already populated, skip it
            current_value = getattr(self, field_name)
            if current_value is not None:
                continue

            if field_name not in self_field_names:
                raise AttributeError(
                    f"field with name '{field_name}' not found in {self.__class__.__name__}"
                )

            # Fill the current field with the default value
            default_value = getattr(default_model, field_name)
            setattr(self, field_name, default_value)

        return self


class Process(models.TextChoices):
    """
    Process TextChoices for Crew model
    """

    SEQUENTIAL = "sequential"
    HIERARCHICAL = "hierarchical"


class DefaultBaseModel(models.Model):
    """
    Singleton base model for models that intended to be defaults
    """

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super(DefaultBaseModel, self).save(*args, **kwargs)

    @classmethod
    def load(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class MessageType(Enum):
    AGENT = "agent"
    TASK = "task"
    USER = "user"


class EmbedderTask(models.TextChoices):
    """
    Task type for EmbeddingConfig model
    """

    RETRIEVAL_DOC = "retrieval_document"


class BaseSessionMessage(models.Model):
    session = models.ForeignKey("Session", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    node_name = models.CharField(default="")
    execution_order = models.IntegerField(default=0)

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=["session", "created_at"]),
        ]


class CrewSessionMessage(BaseSessionMessage):
    crew = models.ForeignKey("Crew", on_delete=models.SET_NULL, null=True, default=None)

    class Meta:
        abstract = True


class TimestampMixin(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class MetadataMixin(models.Model):
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True


class ContentHashMixin(models.Model):
    content_hash = models.CharField(max_length=64, editable=False, null=True)

    class Meta:
        abstract = True

    def generate_hash(self):
        """
        Generates a SHA-256 hash.
        """

        excluded_fields = ["id", "created_at", "updated_at", "content_hash", "metadata"]

        data = {
            f.name: str(getattr(self, f.name))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }

        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()

    def save(self, *args, **kwargs):
        self.content_hash = self.generate_hash()
        super().save(*args, **kwargs)


class BaseGraphEntity(TimestampMixin, MetadataMixin, ContentHashMixin):
    class Meta:
        abstract = True


class NextVal(Func):
    """
    Helper to tell Django to use the SQL function 'nextval'.
    Required for Django 5.0+ to automate the migration generation.
    """

    function = "nextval"
    template = "%(function)s(%(expressions)s)"


class BaseGlobalNode(models.Model):
    """
    Abstract base class for all nodes.
    Manages global ID sequence and provides cross-table lookup logic.
    """

    id = models.BigIntegerField(
        primary_key=True,
        db_default=NextVal(Value("tables_global_node_seq")),
        editable=False,
    )

    # node_name = models.CharField(max_length=255, blank=True)

    class Meta:
        abstract = True

    @classmethod
    def get_all_node_models(cls):
        """
        Safely finds all non-abstract Django models inheriting from BaseGlobalNode.
        """
        node_models = []
        for model in apps.get_models():
            if issubclass(model, cls) and not model._meta.abstract:
                node_models.append(model)
        return node_models

    @classmethod
    def find_globally(cls, node_id) -> Self:
        """
        Executes a single SQL UNION query to find which table contains the given ID
        and returns the actual model instance.
        """
        node_models = cls.get_all_node_models()
        if not node_models:
            return None

        # Map table names to model classes for quick reverse lookup
        table_to_model = {m._meta.db_table: m for m in node_models}
        tables = list(table_to_model.keys())

        # Build UNION ALL query: SELECT 'table_name' as tbl FROM table_name WHERE id = %s
        union_parts = [f"SELECT '{t}' as tbl FROM {t} WHERE id = %s" for t in tables]
        query = " UNION ALL ".join(union_parts)
        params = [node_id] * len(tables)

        with connection.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()

        if row:
            table_name = row[0]
            target_model = table_to_model[table_name]
            return target_model.objects.get(id=node_id)

        return None
