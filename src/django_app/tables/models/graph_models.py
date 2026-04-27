import hashlib
import json
import uuid

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.utils import timezone
from loguru import logger

from tables.models.base_models import (
    BaseGlobalNode,
    BaseGraphEntity,
    TimestampMixin,
    ContentHashMixin,
    SoftDeleteMixin,
)
from tables.models.label_models import Label


class GraphManager(models.Manager):
    def get_transitive_subflows(self, graph_id):
        """Return a queryset of all transitively referenced subgraphs using a recursive CTE."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE subgraph_tree AS (
                    SELECT sn.subgraph_id
                    FROM tables_subgraphnode sn
                    WHERE sn.graph_id = %s
                    UNION
                    SELECT sn.subgraph_id
                    FROM tables_subgraphnode sn
                    INNER JOIN subgraph_tree st ON sn.graph_id = st.subgraph_id
                )
                SELECT subgraph_id FROM subgraph_tree
                """,
                [graph_id],
            )
            subgraph_ids = [row[0] for row in cursor.fetchall()]

        return self.filter(id__in=subgraph_ids).prefetch_related("tags")


class Graph(TimestampMixin, models.Model):
    objects = GraphManager()

    tags = models.ManyToManyField(to="GraphTag", blank=True, default=[])
    labels = models.ManyToManyField(Label, blank=True, related_name="flows")

    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    name = models.CharField(max_length=255, blank=False, unique=True)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    time_to_live = models.IntegerField(
        default=3600, help_text="Session lifitime duration in seconds."
    )
    persistent_variables = models.BooleanField(
        default=False, help_text="If 'True' -> use variables from last session."
    )
    epicchat_enabled = models.BooleanField(
        default=False, help_text="If 'True' -> flow is connected to EpicChat widget."
    )


class BaseNode(BaseGraphEntity, BaseGlobalNode):
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE)
    node_name = models.CharField(max_length=255, blank=True)
    input_map = models.JSONField(default=dict)
    output_variable_path = models.CharField(
        max_length=255, blank=True, null=True, default=None
    )

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self.node_name:
            super().save(*args, **kwargs)
            self.node_name = f"{self.__class__.__name__.lower()}_{self.pk}"
            kwargs.pop("force_insert", None)  # Remove `force_insert` if present
            kwargs["force_update"] = True  # Ensure only update happens
        super().save(*args, **kwargs)


class CrewNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="crew_node_list"
    )
    crew = models.ForeignKey("Crew", on_delete=models.CASCADE)
    stream_config = models.JSONField(default=dict, blank=True)


class PythonNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="python_node_list"
    )
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)
    stream_config = models.JSONField(default=dict, blank=True)

    def generate_hash(self):
        """
        Generates a SHA-256 hash.
        """

        excluded_fields = [
            "id",
            "created_at",
            "updated_at",
            "content_hash",
            "metadata",
            "python_code",
        ]

        data = {
            f.name: str(getattr(self, f.name))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }
        nested_python_code_hash = self.python_code.content_hash

        data["python_code"] = nested_python_code_hash

        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()


class FileExtractorNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="file_extractor_node_list"
    )


class AudioTranscriptionNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="audio_transcription_node_list"
    )


class LLMNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="llm_node_list"
    )
    llm_config = models.ForeignKey("LLMConfig", blank=False, on_delete=models.CASCADE)


class EndNode(BaseGraphEntity, BaseGlobalNode):
    # TODO: can be OneToOne field
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="end_node"
    )
    output_map = models.JSONField()

    @property
    def node_name(self):
        return "__end_node__"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["graph"], name="unique_graph_end_node")
        ]

    def clean(self):
        super().clean()
        if not self.output_map:
            self.output_map = {"context": "variables"}
            logger.debug('Set default output_map to {"context": "variables"}')

    def save(self, *args, **kwargs):
        if not self.output_map:
            self.output_map = {"context": "variables"}
            logger.debug('Set default output_map to {"context": "variables"}')
        super().save(*args, **kwargs)


class SubGraphNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="subgraph_node_list"
    )
    subgraph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="as_subgraph"
    )
    # TODO: maybe SET_NULL on delete?


class CodeAgentNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="code_agent_node_list"
    )
    llm_config = models.ForeignKey(
        "LLMConfig", on_delete=models.SET_NULL, null=True, blank=True
    )
    agent_mode = models.CharField(max_length=10, default="build")
    session_id = models.CharField(max_length=255, blank=True, default="")
    system_prompt = models.TextField(blank=True, default="")
    stream_handler_code = models.TextField(blank=True, default="")
    libraries = models.JSONField(default=list, blank=True)
    polling_interval_ms = models.IntegerField(default=1000)
    silence_indicator_s = models.IntegerField(default=3)
    indicator_repeat_s = models.IntegerField(default=5)
    chunk_timeout_s = models.IntegerField(default=30)
    inactivity_timeout_s = models.IntegerField(default=120)
    max_wait_s = models.IntegerField(default=300)
    stream_config = models.JSONField(default=dict, blank=True)
    output_schema = models.JSONField(default=dict, blank=True)


class Edge(BaseGraphEntity, models.Model):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="edge_list"
    )
    start_node_id = models.BigIntegerField(null=False, default=0)
    end_node_id = models.BigIntegerField(null=False, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "start_node_id", "end_node_id"],
                name="unique_graph_edge",
            )
        ]

    def clean(self):
        # Using the unified class method to find any node type by ID
        start_node = BaseGlobalNode.find_globally(self.start_node_id)
        if not start_node:
            raise ObjectDoesNotExist(
                f"Start node with ID {self.start_node_id} not found."
            )

        end_node = BaseGlobalNode.find_globally(self.end_node_id)
        if not end_node:
            raise ObjectDoesNotExist(f"End node with ID {self.end_node_id} not found.")


class ConditionalEdge(BaseGraphEntity, BaseGlobalNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="conditional_edge_list"
    )

    source_node_id = models.BigIntegerField(null=True, default=None)
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)
    input_map = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "source_node_id"],
                name="unique_graph_conditional_edge_source",
            )
        ]

    def generate_hash(self):
        excluded_fields = [
            "id",
            "created_at",
            "updated_at",
            "content_hash",
            "metadata",
            "python_code",
        ]
        data = {
            f.name: str(getattr(self, f.name))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }
        data["python_code"] = self.python_code.content_hash
        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()

    def clean(self):
        if not BaseGlobalNode.find_globally(self.source_node_id):
            raise ValidationError(
                {
                    "source_node_id": f"Node with ID {self.source_node_id} does not exist."
                }
            )


class GraphSessionMessage(models.Model):
    session = models.ForeignKey("Session", on_delete=models.CASCADE)
    created_at = models.DateTimeField()
    name = models.CharField(default="")
    execution_order = models.IntegerField(default=0)
    message_data = models.JSONField()
    uuid = models.UUIDField(null=False, editable=False, unique=True)


class StartNode(BaseGraphEntity, BaseGlobalNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="start_node_list"
    )
    variables = models.JSONField(default=dict)

    @property
    def node_name(self):
        return "__start__"

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["graph"], name="unique_graph_start_node")
        ]


class DecisionTableNode(BaseGraphEntity, BaseGlobalNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="decision_table_node_list"
    )
    node_name = models.CharField(max_length=255, blank=True)
    default_next_node_id = models.BigIntegerField(null=True, default=None)
    next_error_node_id = models.BigIntegerField(null=True, default=None)

    def generate_hash(self):
        excluded_fields = ["id", "created_at", "updated_at", "content_hash", "metadata"]
        data = {
            f.name: str(getattr(self, f.name))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }
        data["condition_groups"] = sorted(
            cg.content_hash for cg in self.condition_groups.all() if cg.content_hash
        )
        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()

    def clean(self):
        super().clean()

        if self.default_next_node_id:
            default_next_node = BaseGlobalNode.find_globally(self.default_next_node_id)
            if not default_next_node:
                raise ValidationError(
                    {
                        "default_next_node_id": f"Default next node with ID '{self.default_next_node_id}' not found."
                    }
                )

        if self.next_error_node_id:
            next_error_node = BaseGlobalNode.find_globally(self.next_error_node_id)
            if not next_error_node:
                raise ValidationError(
                    {
                        "next_error_node_id": f"Error node with ID '{self.next_error_node_id}' not found."
                    }
                )


class ConditionGroup(ContentHashMixin, models.Model):
    decision_table_node = models.ForeignKey(
        "DecisionTableNode", on_delete=models.CASCADE, related_name="condition_groups"
    )
    group_name = models.CharField(max_length=255, blank=False)
    group_type = models.CharField(max_length=255, blank=False)  # simple, complex
    order = models.PositiveIntegerField(blank=False, default=0)
    expression = models.CharField(max_length=255, null=True, blank=True, default=None)
    manipulation = models.CharField(max_length=255, null=True, blank=True, default=None)

    next_node_id = models.BigIntegerField(null=True, default=None)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["decision_table_node", "group_name"],
                name="unique_decision_table_node_group_name",
            ),
        ]
        ordering = ["order"]

    def generate_hash(self):
        excluded_fields = ["id", "created_at", "updated_at", "content_hash", "metadata"]
        data = {
            f.name: str(getattr(self, f.name))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }
        data["conditions"] = sorted(
            c.content_hash for c in self.conditions.all() if c.content_hash
        )
        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()

    def clean(self):
        super().clean()

        if self.next_node_id:
            next_node = BaseGlobalNode.find_globally(self.next_node_id)
            if not next_node:
                raise ValidationError(
                    {
                        "next_node_id": f"Next node with ID '{self.next_node_id}' not found."
                    }
                )


class Condition(ContentHashMixin, models.Model):
    condition_group = models.ForeignKey(
        "ConditionGroup", on_delete=models.CASCADE, related_name="conditions"
    )
    condition_name = models.CharField(max_length=512, blank=False)
    order = models.PositiveIntegerField(blank=False, default=0)
    condition = models.CharField(max_length=5000, blank=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["condition_group", "condition_name"],
                name="unique_condition_group_condition_name",
            )
        ]
        ordering = ["order"]


class GraphFile(models.Model):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="uploaded_files"
    )
    domain_key = models.CharField(
        max_length=100, help_text="Key to access file from domain"
    )
    name = models.CharField(max_length=255, help_text="Original filename")
    content_type = models.CharField(max_length=100, help_text="MIME type")
    size = models.PositiveIntegerField(help_text="File size in bytes")
    file = models.FileField(upload_to="uploads/")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "domain_key"], name="unique_file_key_per_graph"
            )
        ]

    def delete(self, *args, **kwargs):
        if self.file:
            self.file.delete(save=False)

        super().delete(*args, **kwargs)


class Organization(models.Model):
    name = models.CharField(max_length=256, blank=False, unique=True)


class OrganizationUser(models.Model):
    name = models.CharField(max_length=256, blank=False)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["name", "organization"],
                name="unique_flow_user_for_organization",
            )
        ]


class BasePersistentEntity(models.Model):
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE)
    persistent_variables = models.JSONField(
        default=dict,
        help_text="Variables that persistent for specific entity for specific flow",
    )

    class Meta:
        abstract = True


class GraphOrganization(BasePersistentEntity):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="graph"
    )
    user_variables = models.JSONField(
        default=dict,
        help_text="Variables that persistent for all users for specific flow",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "organization"],
                name="unique_organization_per_flow",
            )
        ]


class GraphOrganizationUser(BasePersistentEntity):
    user = models.ForeignKey(
        OrganizationUser, on_delete=models.CASCADE, related_name="graph"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "user"],
                name="unique_user_per_flow",
            )
        ]


class WebhookTriggerNode(BaseGraphEntity, BaseGlobalNode):
    node_name = models.CharField(max_length=255, blank=False)
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="webhook_trigger_node_list"
    )
    webhook_trigger = models.ForeignKey(
        "WebhookTrigger",
        on_delete=models.SET_NULL,
        null=True,
        related_name="webhook_trigger_nodes",
    )
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)

    def generate_hash(self):
        """
        Generates a SHA-256 hash.
        """

        excluded_fields = [
            "id",
            "created_at",
            "updated_at",
            "content_hash",
            "metadata",
            "python_code",
        ]

        data = {
            f.name: str(getattr(self, f.attname))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }
        nested_python_code_hash = self.python_code.content_hash

        data["python_code"] = nested_python_code_hash

        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()


class TelegramTriggerNode(BaseGraphEntity, BaseGlobalNode):
    node_name = models.CharField(max_length=255, blank=False)
    telegram_bot_api_key = models.CharField(
        max_length=255, blank=True, null=True, default=None
    )
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="telegram_trigger_node_list"
    )
    webhook_trigger = models.ForeignKey(
        "WebhookTrigger",
        on_delete=models.SET_NULL,
        null=True,
        related_name="telegram_trigger_nodes",
    )

    def generate_hash(self):
        excluded_fields = ["id", "created_at", "updated_at", "content_hash", "metadata"]
        data = {
            f.name: str(getattr(self, f.attname))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }
        data["fields"] = sorted(
            field.content_hash for field in self.fields.all() if field.content_hash
        )
        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()


class TelegramTriggerNodeField(ContentHashMixin, models.Model):
    telegram_trigger_node = models.ForeignKey(
        TelegramTriggerNode, on_delete=models.CASCADE, related_name="fields"
    )
    parent = models.CharField(max_length=50, blank=False)  # message, callback_query
    field_name = models.CharField(max_length=255, blank=False)
    variable_path = models.CharField(max_length=255, blank=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["telegram_trigger_node", "field_name", "parent"],
                name="unique_telegram_trigger_node_field_name_parent",
            )
        ]


class GraphNote(BaseGraphEntity, BaseGlobalNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="graph_note_list"
    )
    content = models.TextField()


class GraphVersion(SoftDeleteMixin, models.Model):
    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
        related_name="versions",
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    snapshot = models.JSONField(
        help_text="Serialized graph state: nodes, edges, conditional edges, metadata."
    )
    dependencies = models.JSONField(
        default=dict,
        help_text="Lightweight manifest of external dependency IDs referenced at snapshot time.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
