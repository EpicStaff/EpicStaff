from rest_framework import serializers

from tables.models import (
    Graph,
    EndNode,
    StartNode,
    PythonNode,
    DecisionTableNode,
    CrewNode,
    LLMNode,
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
)
from tables.models.graph_models import (
    CodeAgentNode,
    GraphNote,
    ClassificationDecisionTablePrompt,
)
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer


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


class LLMNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = LLMNode
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
        exclude = ["tags", "created_at", "updated_at", "labels"]
