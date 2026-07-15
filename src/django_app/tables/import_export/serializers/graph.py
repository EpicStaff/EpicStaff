from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from tables.models import (
    Graph,
    EndNode,
    StartNode,
    PythonNode,
    DecisionTableNode,
    CrewNode,
    FileExtractorNode,
    WebhookTriggerNode,
    TelegramTriggerNode,
    TelegramTriggerNodeField,
    AudioTranscriptionNode,
    Edge,
    ConditionalEdge,
    PythonCode,
    WebhookTrigger,
    ConditionGroup,
    Condition,
    SubGraphNode,
    ClassificationDecisionTableNode,
    ClassificationConditionGroup,
    TaskNode,
    AgentNode,
)
from tables.models.graph_models import (
    CodeAgentNode,
    GraphNote,
    ScheduleTriggerNode,
    ClassificationDecisionTablePrompt,
)
from tables.import_export.enums import EntityType
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer


def _serialize_inline_surface(inline_surface):
    return {
        "instructions": inline_surface.instructions,
        "tools": {
            EntityType.PYTHON_CODE_TOOL: list(
                inline_surface.python_tools.values("python_tool_id", "mode")
            ),
            EntityType.MCP_TOOL: list(
                inline_surface.mcp_tools.values("mcp_tool_id", "mode")
            ),
        },
    }


class BaseNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )

    class Meta:
        model = None
        exclude = ["created_at", "updated_at"]


class StartNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = StartNode
        exclude = ["created_at", "updated_at"]


class WebhookTriggerNodeImportSerializer(BaseNodeImportSerializer):
    python_code = PythonCodeImportSerializer(required=False)
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        write_only=True,
    )
    webhook_trigger_id = serializers.PrimaryKeyRelatedField(
        queryset=WebhookTrigger.objects.all(),
        source="webhook_trigger",
        write_only=True,
        allow_null=True,
        required=False,
    )

    class Meta(BaseNodeImportSerializer.Meta):
        model = WebhookTriggerNode
        exclude = ["created_at", "updated_at"]


class ConditionImportSerializer(serializers.ModelSerializer):
    condition_group = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Condition
        fields = "__all__"


class ConditionGroupImportSerializer(serializers.ModelSerializer):
    conditions = ConditionImportSerializer(many=True, required=False, read_only=True)
    decision_table_node = serializers.PrimaryKeyRelatedField(read_only=True)
    decision_table_node_id = serializers.PrimaryKeyRelatedField(
        queryset=DecisionTableNode.objects.all(),
        source="decision_table_node",
        write_only=True,
    )

    class Meta:
        model = ConditionGroup
        fields = "__all__"


class DecisionTableNodeImportSerializer(BaseNodeImportSerializer):
    condition_groups = ConditionGroupImportSerializer(
        many=True, required=False, read_only=True
    )

    class Meta(BaseNodeImportSerializer.Meta):
        model = DecisionTableNode
        exclude = ["created_at", "updated_at"]


class ClassificationConditionGroupImportSerializer(serializers.ModelSerializer):
    classification_decision_table_node = serializers.PrimaryKeyRelatedField(
        read_only=True
    )
    classification_decision_table_node_id = serializers.PrimaryKeyRelatedField(
        queryset=ClassificationDecisionTableNode.objects.all(),
        source="classification_decision_table_node",
        write_only=True,
    )

    class Meta:
        model = ClassificationConditionGroup
        fields = "__all__"


class ClassificationDecisionTablePromptImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassificationDecisionTablePrompt
        fields = [
            "prompt_key",
            "prompt_text",
            "llm_config",
            "output_schema",
            "result_variable",
            "variable_mappings",
        ]


class ClassificationDecisionTableNodeImportSerializer(BaseNodeImportSerializer):
    condition_groups = ClassificationConditionGroupImportSerializer(
        many=True, required=False, read_only=True
    )
    prompt_configs = ClassificationDecisionTablePromptImportSerializer(
        many=True, required=False, read_only=True
    )
    pre_python_code = PythonCodeImportSerializer(
        read_only=True, required=False, allow_null=True
    )
    pre_python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="pre_python_code",
        write_only=True,
        required=False,
        allow_null=True,
    )
    post_python_code = PythonCodeImportSerializer(
        read_only=True, required=False, allow_null=True
    )
    post_python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="post_python_code",
        write_only=True,
        required=False,
        allow_null=True,
    )

    class Meta(BaseNodeImportSerializer.Meta):
        model = ClassificationDecisionTableNode
        exclude = ["created_at", "updated_at", "prompts"]


class TelegramTriggerNodeFieldImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramTriggerNodeField
        exclude = ["telegram_trigger_node"]


class TelegramTriggerNodeImportSerializer(BaseNodeImportSerializer):
    fields = TelegramTriggerNodeFieldImportSerializer(many=True, read_only=True)

    class Meta:
        model = TelegramTriggerNode
        exclude = ["created_at", "updated_at", "telegram_bot_api_key"]


class PythonNodeImportSerializer(BaseNodeImportSerializer):
    python_code = PythonCodeImportSerializer(read_only=True)
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        write_only=True,
    )

    class Meta(BaseNodeImportSerializer.Meta):
        model = PythonNode
        exclude = ["created_at", "updated_at"]


class EndNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = EndNode
        exclude = ["created_at", "updated_at"]


class FileExtractorNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = FileExtractorNode
        exclude = ["created_at", "updated_at"]


class AudioTranscriptionNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = AudioTranscriptionNode
        exclude = ["created_at", "updated_at"]


class CrewNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = CrewNode
        exclude = ["created_at", "updated_at"]


class SubgraphNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = SubGraphNode
        exclude = ["created_at", "updated_at"]


class CodeAgentNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = CodeAgentNode
        exclude = ["created_at", "updated_at"]


class GraphNoteImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = GraphNote
        exclude = ["created_at", "updated_at"]


class TaskNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = TaskNode
        exclude = ["created_at", "updated_at", "surface_list"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["surface_list"] = list(instance.surface_list.values_list("id", flat=True))

        try:
            ret["inline_surface"] = _serialize_inline_surface(instance.inline_surface)
        except ObjectDoesNotExist:
            ret["inline_surface"] = None

        return ret


class AgentNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = AgentNode
        exclude = ["created_at", "updated_at", "surface_list"]

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        ret["surface_list"] = list(instance.surface_list.values_list("id", flat=True))

        try:
            ret["inline_surface"] = _serialize_inline_surface(instance.inline_surface)
        except ObjectDoesNotExist:
            ret["inline_surface"] = None

        ret["tasks"] = [
            {
                "id": task.id,
                "name": task.name,
                "order": task.order,
                "instructions": task.instructions,
                "output_schema": task.output_schema,
                "context_tasks": list(task.context_tasks.values_list("id", flat=True)),
            }
            for task in instance.tasks.all()
        ]

        return ret


class EdgeImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Edge
        exclude = ["created_at", "updated_at"]


class ConditionalEdgeImportSerializer(serializers.ModelSerializer):
    python_code = PythonCodeImportSerializer(read_only=True)
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        write_only=True,
    )

    class Meta:
        model = ConditionalEdge
        exclude = ["created_at", "updated_at"]


class GraphImportSerializer(serializers.ModelSerializer):
    edge_list = EdgeImportSerializer(many=True, read_only=True)
    conditional_edge_list = ConditionalEdgeImportSerializer(many=True, read_only=True)
    nodes = serializers.JSONField(required=False)

    class Meta:
        model = Graph
        exclude = ["tags", "created_at", "updated_at", "labels", "save_version"]


class ScheduleTriggerNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = ScheduleTriggerNode
        exclude = ["created_at", "updated_at"]

    def create(self, validated_data):
        # Schedule config is preserved verbatim; activation state is reset so
        # an imported flow never starts firing on its own — user must enable
        # it explicitly after reviewing the imported schedule.
        validated_data["is_active"] = False
        validated_data["current_runs"] = 0
        validated_data["next_run_date_time"] = None
        return super().create(validated_data)
