import hashlib
import json
import uuid

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import models
from django.db.models import F
from django.utils import timezone
from loguru import logger

from tables.models.base_models import (
    ActiveManager,
    BaseGlobalNode,
    BaseGraphEntity,
    TimestampMixin,
    ContentHashMixin,
    SoftDeleteFields,
    SoftDeleteMixin,
    soft_delete_consistency_constraint,
)
from tables.models.label_models import Label
from tables.models.rbac_models.org_scoped import OrgScopedModel
from tables.exceptions import GraphSaveVersionConflictError
from tables.models.knowledge_models.graphrag_models import AgentGraphRag
from tables.models.knowledge_models.collection_models import BaseRagType


class GraphManager(ActiveManager):
    def get_transitive_subflows(self, graph_id):
        """Return a queryset of all transitively referenced subgraphs using a recursive CTE."""
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                """
                WITH RECURSIVE subgraph_tree AS (
                    SELECT sn.subgraph_id
                    FROM tables_subgraphnode sn
                    WHERE sn.graph_id = %s AND sn.is_soft_deleted = false
                    UNION
                    SELECT sn.subgraph_id
                    FROM tables_subgraphnode sn
                    INNER JOIN subgraph_tree st ON sn.graph_id = st.subgraph_id
                    WHERE sn.is_soft_deleted = false
                )
                SELECT subgraph_id FROM subgraph_tree
                """,
                [graph_id],
            )
            subgraph_ids = [row[0] for row in cursor.fetchall()]

        return self.filter(id__in=subgraph_ids).prefetch_related("tags")


class Graph(OrgScopedModel, TimestampMixin, SoftDeleteMixin):
    objects = GraphManager()
    all_objects = models.Manager()

    tags = models.ManyToManyField(to="GraphTag", blank=True, default=[])
    labels = models.ManyToManyField(Label, blank=True, related_name="flows")

    uuid = models.UUIDField(default=uuid.uuid4, unique=True)
    name = models.CharField(max_length=255, blank=False)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    time_to_live = models.IntegerField(
        default=3600, help_text="Session lifitime duration in seconds."
    )
    enable_persistent_variables = models.BooleanField(
        default=False, help_text="If 'True' -> use variables from last session."
    )
    epicchat_enabled = models.BooleanField(
        default=False, help_text="If 'True' -> flow is connected to EpicChat widget."
    )
    save_version = models.BigIntegerField(default=1)

    @classmethod
    def increment_version_if_current(cls, pk: int, expected: int) -> int:
        """
        Atomically increment save_version if the row's current save_version equals `expected`.
        Returns the new save_version on success. Raises GraphSaveVersionConflictError on mismatch.
        Must be called inside a transaction.atomic block by the caller.
        """

        updated = cls.objects.filter(pk=pk, save_version=expected).update(
            save_version=F("save_version") + 1
        )
        if not updated:
            current = (
                cls.objects.filter(pk=pk).values_list("save_version", flat=True).first()
            )
            raise GraphSaveVersionConflictError(current_version=current)
        return expected + 1

    class Meta(OrgScopedModel.Meta):
        abstract = False
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["org", "name"],
                condition=models.Q(is_soft_deleted=False),
                name="unique_graph_name_per_org",
            ),
        ]


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
            self.__class__.objects.filter(pk=self.pk).update(node_name=self.node_name)
            return
        super().save(*args, **kwargs)


class CrewNode(BaseNode, SoftDeleteFields):
    """
    DEPRECATED: CrewNode is deprecated. Use AgentNode or TaskNode instead.
    New flows must not create CrewNodes; this model exists only for backward
    compatibility with existing graphs.
    """

    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="crew_node_list"
    )
    crew = models.ForeignKey("Crew", on_delete=models.CASCADE)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class PythonNode(BaseNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="python_node_list"
    )
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)
    test_input = models.JSONField(default=dict, blank=True)
    use_storage = models.BooleanField(default=False)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

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
            "test_input",
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


class KnowledgeNode(BaseNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="knowledge_node_list"
    )
    source_collection = models.ForeignKey(
        "SourceCollection", on_delete=models.SET_NULL, null=True, blank=True
    )
    # RAG addressed the same way as the agent path and the knowledge service:
    # a type name ("naive"/"graph") plus the impl id surfaced by /available-rags.
    rag_type = models.CharField(
        max_length=30,
        choices=BaseRagType.RagType.choices,
        null=True,
        blank=True,
        default=None,
    )
    rag_id = models.IntegerField(null=True, blank=True, default=None)
    query = models.TextField(blank=True, default="")
    search_method = models.CharField(
        max_length=10,
        choices=AgentGraphRag.SearchMethod.choices,
        null=True,
        blank=True,
        default=None,
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class FileExtractorNode(BaseNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="file_extractor_node_list"
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class AudioTranscriptionNode(BaseNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="audio_transcription_node_list"
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class EndNode(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
    # TODO: can be OneToOne field
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="end_node"
    )
    output_map = models.JSONField()

    @property
    def node_name(self):
        return "__end_node__"

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(fields=["graph"], name="unique_graph_end_node"),
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


class SubGraphNode(BaseNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="subgraph_node_list"
    )
    subgraph = models.ForeignKey(
        "Graph",
        on_delete=models.SET_NULL,
        related_name="as_subgraph",
        null=True,
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class Edge(BaseGraphEntity, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="edge_list"
    )
    start_node_id = models.BigIntegerField(null=False, default=0)
    end_node_id = models.BigIntegerField(null=False, default=0)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["graph", "start_node_id", "end_node_id"],
                name="unique_graph_edge",
            ),
        ]

    def clean(self):
        # Start/end nodes must exist AND belong to this edge's graph (which also
        # keeps them in the same org). A node in another graph/org is treated as
        # not found.
        start_node = BaseGlobalNode.find_globally(self.start_node_id)
        if not start_node or start_node.graph_id != self.graph_id:
            raise ObjectDoesNotExist(
                f"Start node with ID {self.start_node_id} not found."
            )

        end_node = BaseGlobalNode.find_globally(self.end_node_id)
        if not end_node or end_node.graph_id != self.graph_id:
            raise ObjectDoesNotExist(f"End node with ID {self.end_node_id} not found.")


class ConditionalEdge(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="conditional_edge_list"
    )

    source_node_id = models.BigIntegerField(null=True, default=None)
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)
    input_map = models.JSONField(default=dict)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["graph", "source_node_id"],
                name="unique_graph_conditional_edge_source",
            ),
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
    parent_subgraph_execution_id = models.UUIDField(
        null=True, blank=True, db_index=True
    )

    class Meta:
        indexes = [
            models.Index(
                fields=["session", "parent_subgraph_execution_id", "id"],
                name="gsm_session_parent_id_idx",
            ),
        ]


class StartNode(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="start_node_list"
    )
    variables = models.JSONField(default=dict)

    @property
    def node_name(self):
        return "__start__"

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(fields=["graph"], name="unique_graph_start_node"),
        ]


class DecisionTableNode(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="decision_table_node_list"
    )
    node_name = models.CharField(max_length=255, blank=True)
    default_next_node_id = models.BigIntegerField(null=True, default=None)
    next_error_node_id = models.BigIntegerField(null=True, default=None)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

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
            if not default_next_node or default_next_node.graph_id != self.graph_id:
                raise ValidationError(
                    {
                        "default_next_node_id": f"Default next node with ID '{self.default_next_node_id}' not found."
                    }
                )

        if self.next_error_node_id:
            next_error_node = BaseGlobalNode.find_globally(self.next_error_node_id)
            if not next_error_node or next_error_node.graph_id != self.graph_id:
                raise ValidationError(
                    {
                        "next_error_node_id": f"Error node with ID '{self.next_error_node_id}' not found."
                    }
                )


class ConditionGroup(ContentHashMixin, SoftDeleteFields):
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
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
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
            # Same graph as the owning decision table (⇒ same org).
            owner_graph_id = getattr(self.decision_table_node, "graph_id", None)
            if not next_node or next_node.graph_id != owner_graph_id:
                raise ValidationError(
                    {
                        "next_node_id": f"Next node with ID '{self.next_node_id}' not found."
                    }
                )


class Condition(ContentHashMixin, SoftDeleteFields):
    condition_group = models.ForeignKey(
        "ConditionGroup", on_delete=models.CASCADE, related_name="conditions"
    )
    condition_name = models.CharField(max_length=512, blank=False)
    order = models.PositiveIntegerField(blank=False, default=0)
    condition = models.CharField(max_length=5000, blank=False)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["condition_group", "condition_name"],
                name="unique_condition_group_condition_name",
            ),
        ]
        ordering = ["order"]


# Legacy graph-domain `Organization` and `OrganizationUser` (anonymous named
# flow end-users) were replaced by the RBAC models `Organization` and
# `OrganizationUser` (see tables/models/rbac_models/). GraphOrganization and
# GraphOrganizationUser below now hold per-flow persistent variables scoped to
# those RBAC entities.
#
# - GraphOrganization(graph)                         -> org-level persistent vars
#   .user_variables                                 -> seed template for new
#                                                      GraphOrganizationUser rows
# - GraphOrganizationUser(graph, organization_user) -> per-membership persistent
#                                                      vars (one User in one Org)


class BasePersistentEntity(models.Model):
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE)
    persistent_variables = models.JSONField(
        default=dict,
        help_text="Variables that persistent for specific entity for specific flow",
    )

    class Meta:
        abstract = True


class GraphOrganization(BasePersistentEntity, SoftDeleteFields):
    # Org is derived from graph.org (a flow has exactly one owning org), so this
    # row is a 1:1 extension of Graph holding org-level persistent variables.
    # TODO refactor to use user_variable for persistent variables
    user_variables = models.JSONField(
        default=dict,
        help_text="Seed template of variables copied into each user's GraphOrganizationUser row",
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["graph"],
                name="unique_persistent_state_per_flow",
            ),
        ]


class GraphOrganizationUser(BasePersistentEntity, SoftDeleteFields):
    # FK points at RBAC OrganizationUser (User x Org membership), so per-user
    # persistent state is scoped per-org as well
    # TODO refactor to use user_variable for persistent variables
    organization_user = models.ForeignKey(
        "OrganizationUser",
        on_delete=models.CASCADE,
        related_name="graph_persistent_states",
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["graph", "organization_user"],
                name="unique_user_per_flow",
            ),
        ]


class WebhookTriggerNode(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
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

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

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


class TelegramTriggerNode(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
    node_name = models.CharField(max_length=255, blank=False)
    telegram_bot_api_key_secret = models.ForeignKey(
        "Secret",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="telegram_trigger_nodes",
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

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

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


class TelegramTriggerNodeField(ContentHashMixin, SoftDeleteFields):
    telegram_trigger_node = models.ForeignKey(
        TelegramTriggerNode, on_delete=models.CASCADE, related_name="fields"
    )
    parent = models.CharField(max_length=50, blank=False)  # message, callback_query
    field_name = models.CharField(max_length=255, blank=False)
    variable_path = models.CharField(max_length=255, blank=False)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["telegram_trigger_node", "field_name", "parent"],
                name="unique_telegram_trigger_node_field_name_parent",
            ),
        ]


class ScheduleTriggerNode(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
    class RunMode(models.TextChoices):
        ONCE = "once", "Once"
        REPEAT = "repeat", "Repeat"

    class TimeUnit(models.TextChoices):
        SECONDS = "seconds", "Seconds"
        MINUTES = "minutes", "Minutes"
        HOURS = "hours", "Hours"
        DAYS = "days", "Days"
        WEEKS = "weeks", "Weeks"
        MONTHS = "months", "Months"

    class EndType(models.TextChoices):
        NEVER = "never", "Never"
        ON_DATE = "on_date", "On Date"
        AFTER_N_RUNS = "after_n_runs", "After N Runs"

    ALLOWED_WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}

    node_name = models.CharField(max_length=255, blank=False)
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="schedule_trigger_node_list"
    )
    is_active = models.BooleanField(default=False)
    timezone = models.CharField(max_length=64, default="UTC", blank=True)
    run_mode = models.CharField(
        max_length=10, choices=RunMode.choices, null=True, blank=True
    )
    start_date_time = models.DateTimeField(null=True, blank=True)
    every = models.IntegerField(null=True, blank=True)
    unit = models.CharField(
        max_length=10, null=True, blank=True, choices=TimeUnit.choices
    )
    weekdays = models.JSONField(null=True, blank=True)
    end_type = models.CharField(
        max_length=15, choices=EndType.choices, null=True, blank=True
    )
    end_date_time = models.DateTimeField(null=True, blank=True)
    max_runs = models.IntegerField(null=True, blank=True)
    current_runs = models.IntegerField(default=0)
    next_run_date_time = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]

    def generate_hash(self):
        excluded_fields = [
            "id",
            "created_at",
            "updated_at",
            "content_hash",
            "metadata",
            "current_runs",
            "next_run_date_time",
        ]
        data = {
            f.name: str(getattr(self, f.attname))
            for f in self._meta.fields
            if f.name not in excluded_fields
        }
        data_string = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
        return hashlib.sha256(data_string).hexdigest()


class ClassificationDecisionTableNode(
    BaseGraphEntity, BaseGlobalNode, SoftDeleteFields
):
    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
        related_name="classification_decision_table_node_list",
    )
    node_name = models.CharField(max_length=255, blank=True)
    pre_python_code = models.ForeignKey(
        "PythonCode",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="cdt_pre_nodes",
    )
    pre_input_map = models.JSONField(default=dict, blank=True)
    pre_output_variable_path = models.CharField(
        max_length=512, null=True, default=None, blank=True
    )
    post_python_code = models.ForeignKey(
        "PythonCode",
        on_delete=models.CASCADE,
        null=True,
        default=None,
        related_name="cdt_post_nodes",
    )
    post_input_map = models.JSONField(default=dict, blank=True)
    post_output_variable_path = models.CharField(
        max_length=512, null=True, default=None, blank=True
    )
    prompts = models.JSONField(default=dict, blank=True)
    default_llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cdt_nodes_as_default",
    )
    default_next_node_id = models.BigIntegerField(null=True, default=None)
    next_error_node_id = models.BigIntegerField(null=True, default=None)

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

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_classification_dt_node",
            ),
        ]


class ClassificationDecisionTablePrompt(TimestampMixin, SoftDeleteFields):
    cdt_node = models.ForeignKey(
        "ClassificationDecisionTableNode",
        on_delete=models.CASCADE,
        related_name="prompt_configs",
    )
    prompt_key = models.CharField(max_length=255)
    prompt_text = models.TextField(blank=True, default="")
    llm_config = models.ForeignKey(
        "LLMConfig",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cdt_prompts",
    )
    output_schema = models.JSONField(default=dict, blank=True)
    result_variable = models.CharField(max_length=255, default="prompt_result")
    variable_mappings = models.JSONField(default=dict, blank=True)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]
        unique_together = ("cdt_node", "prompt_key")


class ClassificationConditionGroup(BaseGraphEntity, SoftDeleteFields):
    classification_decision_table_node = models.ForeignKey(
        "ClassificationDecisionTableNode",
        on_delete=models.CASCADE,
        related_name="condition_groups",
    )
    group_name = models.CharField(max_length=255, blank=False)
    order = models.PositiveIntegerField(blank=False, default=0)
    expression = models.TextField(null=True, default=None, blank=True)
    prompt = models.ForeignKey(
        "ClassificationDecisionTablePrompt",
        on_delete=models.SET_NULL,
        null=True,
        default=None,
        related_name="condition_groups",
    )
    manipulation = models.TextField(null=True, default=None, blank=True)
    continue_flag = models.BooleanField(default=False)
    next_node_id = models.BigIntegerField(null=True, default=None)
    dock_visible = models.BooleanField(default=True)
    field_expressions = models.JSONField(default=dict, blank=True)
    field_manipulations = models.JSONField(default=dict, blank=True)
    route_code = models.CharField(max_length=128, null=True, default=None, blank=True)
    section = models.CharField(max_length=128, null=True, default=None, blank=True)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        ordering = ["order"]
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["classification_decision_table_node", "route_code"],
                condition=models.Q(route_code__isnull=False),
                name="unique_route_code_per_cdt_node",
            ),
        ]

    def clean(self):
        super().clean()

        if self.next_node_id is not None:
            next_node = BaseGlobalNode.find_globally(self.next_node_id)
            if not next_node:
                raise ValidationError(
                    {
                        "next_node_id": f"Error node with ID '{self.next_node_id}' not found."
                    }
                )


class GraphNote(BaseGraphEntity, BaseGlobalNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="graph_note_list"
    )
    content = models.TextField()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class GraphVersion(SoftDeleteMixin):
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

    objects = ActiveManager()
    all_objects = models.Manager()

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]
        ordering = ["-created_at"]


class StorageFile(models.Model):
    ITEM_TYPE_CHOICES = [("file", "file"), ("folder", "folder")]

    org = models.ForeignKey(
        "Organization",
        on_delete=models.CASCADE,
        related_name="storage_files",
        help_text="Organization that owns this storage entry.",
    )
    path = models.CharField(
        max_length=1000,
        help_text="Org-relative path, never starts with '/'. Folders end with '/'.",
    )
    name = models.CharField(
        max_length=255, help_text="Last path segment, denormalized for search."
    )
    item_type = models.CharField(
        max_length=6,
        choices=ITEM_TYPE_CHOICES,
        default="file",
        help_text="Whether this row represents a file or a folder.",
    )
    size = models.BigIntegerField(
        null=True,
        blank=True,
        help_text="File size in bytes. NULL for folders or when size is unknown.",
    )
    s3_modified = models.DateTimeField(
        null=True,
        blank=True,
        help_text="LastModified timestamp from the storage backend. NULL when unknown.",
    )
    is_system = models.BooleanField(
        default=False,
        help_text="True for files written by the platform itself (e.g. session outputs). Not filtered yet.",
    )
    parent_path = models.CharField(
        max_length=1000,
        default="",
        help_text="Immediate parent directory path ending in '/', or '' for root entries. Enables single-level listing.",
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        help_text="Timestamp when this DB row was first created.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Timestamp of the last update to this row.",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["org", "path"], name="unique_storage_file_per_org"
            )
        ]
        indexes = [
            models.Index(fields=["org", "path"]),
            models.Index(fields=["org", "parent_path"]),
        ]


class GraphStorageFile(SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="storage_files"
    )
    storage_file = models.ForeignKey(
        "StorageFile", on_delete=models.CASCADE, related_name="graph_storage_files"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["graph", "storage_file"], name="unique_graph_storage_file"
            ),
        ]


class SessionStorageFile(models.Model):
    session = models.ForeignKey(
        "Session", on_delete=models.CASCADE, related_name="storage_files"
    )
    storage_file = models.ForeignKey(
        "StorageFile", on_delete=models.CASCADE, related_name="session_storage_files"
    )
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "storage_file"],
                name="unique_session_storage_file",
            )
        ]


class TaskNode(BaseNode, SoftDeleteFields):
    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
        related_name="task_node_list",
        help_text="Graph this task node belongs to.",
    )
    agent_definition = models.ForeignKey(
        "agents.AgentDefinition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="task_nodes",
        help_text="AgentDefinition that executes this task. Null allowed — runtime surfaces a missing-agent error.",
    )
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Prompt text passed to the agent for this task. Empty means no task-level instructions.",
    )
    output_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="JSON schema the task output must conform to. Empty dict means no schema enforcement.",
    )
    remember_output = models.BooleanField(
        default=False,
        help_text="If True, this task's output is remembered for the current run and injected as context into subsequently executed task nodes in the same session.",
    )
    surface_list = models.ManyToManyField(
        "agents.Surface",
        blank=True,
        related_name="task_nodes",
        help_text="Surfaces attached to this task node.",
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class AgentNode(BaseNode, SoftDeleteFields):
    """Node representing an agent that executes an ordered list of sub-tasks (AgentNodeTask) with shared surfaces."""

    graph = models.ForeignKey(
        "Graph",
        on_delete=models.CASCADE,
        related_name="agent_node_list",
        help_text="Graph this agent node belongs to.",
    )
    agent_definition = models.ForeignKey(
        "agents.AgentDefinition",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        default=None,
        related_name="agent_nodes",
        help_text="AgentDefinition that executes this node's tasks. Null allowed — runtime surfaces a missing-agent error.",
    )
    surface_list = models.ManyToManyField(
        "agents.Surface",
        blank=True,
        related_name="agent_nodes",
        help_text="Surfaces attached to this agent node.",
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        constraints = [soft_delete_consistency_constraint()]


class AgentNodeTask(TimestampMixin, SoftDeleteFields):
    """Child sub-task of an AgentNode; not a graph node — executes sequentially within the parent node."""

    agent_node = models.ForeignKey(
        AgentNode,
        on_delete=models.CASCADE,
        related_name="tasks",
        help_text="Parent AgentNode this task belongs to.",
    )
    name = models.CharField(
        max_length=255,
        help_text="Name of this sub-task, unique within the parent agent node.",
    )
    order = models.PositiveIntegerField(
        help_text="Zero-based position within the parent agent node. Tasks execute in ascending order.",
    )
    instructions = models.TextField(
        blank=True,
        default="",
        help_text="Prompt text passed to the agent for this sub-task. Empty means no task-level instructions.",
    )
    output_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text="Optional JSON schema the task output must conform to. Empty dict = no enforcement.",
    )
    context_tasks = models.ManyToManyField(
        "self",
        symmetrical=False,
        blank=True,
        related_name="dependent_tasks",
        help_text="Earlier sibling tasks whose outputs are injected as context for this task.",
    )

    class Meta:
        default_manager_name = "objects"
        base_manager_name = "all_objects"
        ordering = ["order"]
        constraints = [
            soft_delete_consistency_constraint(),
            models.UniqueConstraint(
                fields=["agent_node", "order"],
                name="uniq_agentnodetask_node_order",
                deferrable=models.Deferrable.DEFERRED,
            ),
            models.UniqueConstraint(
                fields=["agent_node", "name"],
                name="uniq_agentnodetask_node_name",
                deferrable=models.Deferrable.DEFERRED,
            ),
        ]

    def clean(self):
        super().clean()

        if self.pk:
            invalid = self.context_tasks.exclude(agent_node=self.agent_node)

            if invalid.exists():
                raise ValidationError(
                    "context_tasks must belong to the same agent_node."
                )

            forward = self.context_tasks.filter(order__gte=self.order)

            if forward.exists():
                raise ValidationError(
                    "context_tasks must reference tasks with a strictly lower order."
                )
