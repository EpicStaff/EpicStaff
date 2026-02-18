from enum import Enum
import hashlib
import json
from django.db import models
from abc import abstractmethod


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
