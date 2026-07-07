from rest_framework import serializers

from tables.models import (
    Graph,
    ClassificationDecisionTableNode,
    ClassificationConditionGroup,
    PythonCode,
)
from tables.models.graph_models import ClassificationDecisionTablePrompt
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer


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
        exclude = ["created_at", "updated_at"]


class ClassificationDecisionTablePromptImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassificationDecisionTablePrompt
        fields = [
            "id",
            "prompt_key",
            "prompt_text",
            "llm_config",
            "output_schema",
            "result_variable",
            "variable_mappings",
        ]


class ClassificationDecisionTableNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )
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

    class Meta:
        model = ClassificationDecisionTableNode
        exclude = ["created_at", "updated_at", "prompts"]
