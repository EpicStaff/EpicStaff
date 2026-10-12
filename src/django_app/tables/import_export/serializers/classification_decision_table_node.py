from rest_framework import serializers

from tables.import_export.serializers.python_tools import PythonCodeImportSerializer
from tables.models import (
    ClassificationConditionGroup,
    ClassificationDecisionTableNode,
    Graph,
)
from tables.models.graph_models import (
    ClassificationConditionGroupSection,
    ClassificationDecisionTablePrompt,
)
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin


class ClassificationConditionGroupImportSerializer(
    ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer
):
    classification_decision_table_node = serializers.PrimaryKeyRelatedField(read_only=True)
    classification_decision_table_node_id = serializers.PrimaryKeyRelatedField(
        queryset=ClassificationDecisionTableNode.objects.all(),
        source="classification_decision_table_node",
        write_only=True,
    )
    section = serializers.PrimaryKeyRelatedField(
        queryset=ClassificationConditionGroupSection.objects.all(),
        pk_field=serializers.UUIDField(),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = ClassificationConditionGroup
        exclude = ["created_at", "updated_at"]


class ClassificationConditionGroupSectionImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClassificationConditionGroupSection
        fields = ["id", "name", "metadata"]


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


class ClassificationDecisionTableNodeImportSerializer(
    ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer
):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)
    condition_groups = ClassificationConditionGroupImportSerializer(
        many=True, required=False, read_only=True
    )
    sections = ClassificationConditionGroupSectionImportSerializer(
        many=True, required=False, read_only=True
    )
    prompt_configs = ClassificationDecisionTablePromptImportSerializer(
        many=True, required=False, read_only=True
    )
    # Read-only on purpose: PythonCode rows carry no org, so accepting an id here would
    # let an import file attach any existing row. The strategy creates the code from
    # the exported body and passes it to save().
    pre_python_code = PythonCodeImportSerializer(read_only=True, required=False, allow_null=True)
    post_python_code = PythonCodeImportSerializer(read_only=True, required=False, allow_null=True)

    class Meta:
        model = ClassificationDecisionTableNode
        exclude = ["created_at", "updated_at", "created_by", "prompts"]
