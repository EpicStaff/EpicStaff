import uuid
from django.db import models
from django.utils import timezone
from loguru import logger


class Graph(models.Model):
    tags = models.ManyToManyField(to="GraphTag", blank=True, default=[])

    name = models.CharField(max_length=255, blank=False)
    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict)
    time_to_live = models.IntegerField(
        default=3600, help_text="Session lifitime duration in seconds."
    )
    persistent_variables = models.BooleanField(
        default=False, help_text="If 'True' -> use variables from last session."
    )


class BaseNode(models.Model):
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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_crew_node",
            )
        ]


class PythonNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="python_node_list"
    )
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_python_node",
            )
        ]


class FileExtractorNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="file_extractor_node_list"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_file_extractor_node",
            )
        ]


class LLMNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="llm_node_list"
    )
    llm_config = models.ForeignKey("LLMConfig", blank=False, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_llm_node",
            )
        ]


class EndNode(models.Model):
    # TODO: can be OneToOne field
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="end_node"
    )
    output_map = models.JSONField()

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

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_subgraph_node",
            )
        ]


class Edge(models.Model):

    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="edge_list"
    )
    start_key = models.CharField(max_length=255, blank=False)
    end_key = models.CharField(max_length=255, blank=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "start_key", "end_key"], name="unique_graph_edge"
            )
        ]


class ConditionalEdge(models.Model):

    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="conditional_edge_list"
    )
    source = models.CharField(max_length=255, blank=False)
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)
    then = models.CharField(max_length=255, null=True, default=None)
    input_map = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "source"], name="unique_graph_conditional_edge_source"
            )
        ]


class GraphSessionMessage(models.Model):
    session = models.ForeignKey("Session", on_delete=models.CASCADE)
    created_at = models.DateTimeField()
    name = models.CharField(default="")
    execution_order = models.IntegerField(default=0)
    message_data = models.JSONField()
    uuid = models.UUIDField(null=False, editable=False, unique=True)


class StartNode(models.Model):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="start_node_list"
    )
    variables = models.JSONField(default=dict)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["graph"], name="unique_graph_start_node")
        ]


class DecisionTableNode(models.Model):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="decision_table_node_list"
    )
    node_name = models.CharField(max_length=255, blank=True)
    default_next_node = models.CharField(max_length=255, null=True, default=None)
    next_error_node = models.CharField(max_length=255, null=True, default=None)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_decision_table_node",
            )
        ]


class ConditionGroup(models.Model):
    decision_table_node = models.ForeignKey(
        "DecisionTableNode", on_delete=models.CASCADE, related_name="condition_groups"
    )
    group_name = models.CharField(max_length=255, blank=False)

    group_type = models.CharField(max_length=255, blank=False)  # simple, complex
    order = models.PositiveIntegerField(blank=False, default=0)
    expression = models.CharField(max_length=255, null=True, default=None)
    manipulation = models.CharField(max_length=255, null=True, default=None)
    next_node = models.CharField(max_length=255, null=True, default=None)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["decision_table_node", "group_name"],
                name="unique_decision_table_node_group_name",
            ),
        ]
        ordering = ["order"]


class Condition(models.Model):
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


class WebhookTriggerNode(models.Model):
    node_name = models.CharField(max_length=255, blank=False)
    graph = models.ForeignKey("Graph", on_delete=models.CASCADE, related_name="webhook_trigger_node_list")
    webhook_trigger = models.ForeignKey(
        "WebhookTrigger",
        on_delete=models.SET_NULL,
        null=True,
        related_name="webhook_trigger_nodes",
    )
    python_code = models.ForeignKey("PythonCode", on_delete=models.CASCADE)
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["graph", "node_name"],
                name="unique_graph_node_name_for_webhook_nodes",
            )
        ]