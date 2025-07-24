import uuid
from django.db import models
from django.utils import timezone


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


class DecisionTableNode(BaseNode):
    graph = models.ForeignKey(
        "Graph", on_delete=models.CASCADE, related_name="decision_table_node_list"
    )
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
