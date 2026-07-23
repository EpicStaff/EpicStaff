from rest_framework import serializers
from django.db import transaction

from tables.serializers.model_serializers.python_serializers import PythonCodeSerializer
from tables.models.graph_models import (
    Condition,
    ConditionGroup,
    ConditionalEdge,
    DecisionTableNode,
    EndNode,
    StartNode,
    ClassificationDecisionTableNode,
    ClassificationConditionGroup,
    ClassificationDecisionTablePrompt,
)
from tables.models.python_models import PythonCode
from tables.models.llm_models import LLMConfig
from tables.models.graph_models import Graph
from tables.serializers.base_serializer import (
    BaseGraphEntityMixin,
    ContentHashWritableMixin,
)
from tables.serializers.org_scoped_fields import OrgScopedPrimaryKeyRelatedField
from tables.serializers.utils.mixins import (
    NestedPythonCodeMixin,
    assert_node_ref_in_graph,
)
from tables.services.persistent_variables_service import (
    PersistentVariablesService,
)
from tables.services.classification_decision_table_node_children import (
    sync_classification_decision_table_children,
)


class ConditionalEdgeSerializer(
    ContentHashWritableMixin, NestedPythonCodeMixin, serializers.ModelSerializer
):
    python_code = PythonCodeSerializer()
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = ConditionalEdge
        fields = "__all__"


class StartNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    node_name = serializers.SerializerMethodField(read_only=True)
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = StartNode
        fields = [
            "id",
            "graph",
            "variables",
            "node_name",
        ] + BaseGraphEntityMixin.Meta.common_fields
        read_only_fields = ["node_name"]

    def get_node_name(self, obj):
        return "__start__"

    def validate(self, attrs):
        PersistentVariablesService().validate_start_node_variables(
            attrs.get("variables")
        )
        return super().validate(attrs)

    @transaction.atomic
    def create(self, validated_data):
        instance = super().create(validated_data)
        PersistentVariablesService().sync_from_start_node(
            instance.graph, {}, instance.variables or {}
        )
        return instance

    @transaction.atomic
    def update(self, instance, validated_data):
        old_variables = instance.variables.copy() if instance.variables else {}
        instance = super().update(instance, validated_data)
        PersistentVariablesService().sync_from_start_node(
            instance.graph, old_variables, instance.variables or {}
        )
        return instance


class EndNodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    node_name = serializers.SerializerMethodField(read_only=True)
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta(BaseGraphEntityMixin.Meta):
        model = EndNode
        fields = [
            "id",
            "graph",
            "output_map",
            "node_name",
        ] + BaseGraphEntityMixin.Meta.common_fields
        read_only_fields = ["node_name"]

    def get_node_name(self, obj):
        return "__end_node__"


class ConditionSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    condition_group = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Condition
        fields = "__all__"


class ConditionGroupSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    conditions = ConditionSerializer(many=True, required=False)
    decision_table_node = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = ConditionGroup
        fields = "__all__"


class DecisionTableNodeSerializer(
    ContentHashWritableMixin, serializers.ModelSerializer
):
    condition_groups = ConditionGroupSerializer(many=True, required=False)
    graph = OrgScopedPrimaryKeyRelatedField(queryset=Graph.objects.all())

    class Meta:
        model = DecisionTableNode
        fields = "__all__"

    def validate(self, attrs):
        # default/error next nodes and each condition group's next node must live
        # in the same graph as this decision table (same org). Raw int refs.
        graph = attrs.get("graph") or getattr(self.instance, "graph", None)
        for field in ("default_next_node_id", "next_error_node_id"):
            node_id = attrs.get(field, getattr(self.instance, field, None))
            assert_node_ref_in_graph(node_id, graph, field)
        for group in attrs.get("condition_groups", []) or []:
            assert_node_ref_in_graph(
                group.get("next_node_id"), graph, "condition_groups.next_node_id"
            )
        return attrs


def validate_classification_condition_group_names(condition_groups_data) -> list[str]:
    """Return a list of error strings for any group with a blank/null group_name."""
    errors = []

    for idx, group in enumerate(condition_groups_data or []):
        name = group.get("group_name")

        if name is None or (isinstance(name, str) and not name.strip()):
            errors.append(f"condition_groups[{idx}]: group_name may not be blank.")

    return errors


class ClassificationConditionGroupSerializer(serializers.ModelSerializer):
    classification_decision_table_node = serializers.PrimaryKeyRelatedField(
        read_only=True
    )
    prompt = serializers.PrimaryKeyRelatedField(
        queryset=ClassificationDecisionTablePrompt.objects.all(),
        required=False,
        allow_null=True,
    )
    prompt_key = serializers.SerializerMethodField()

    def get_prompt_key(self, obj):
        return obj.prompt.prompt_key if obj.prompt else None

    class Meta:
        model = ClassificationConditionGroup
        fields = "__all__"


class ClassificationDecisionTablePromptSerializer(serializers.ModelSerializer):
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


class ClassificationDecisionTableNodeSerializer(serializers.ModelSerializer):
    condition_groups = ClassificationConditionGroupSerializer(many=True, required=False)
    prompt_configs = ClassificationDecisionTablePromptSerializer(
        many=True, required=False
    )
    pre_python_code = PythonCodeSerializer(required=False, allow_null=True)
    post_python_code = PythonCodeSerializer(required=False, allow_null=True)
    default_llm_config = serializers.PrimaryKeyRelatedField(
        queryset=LLMConfig.objects.all(), required=False, allow_null=True
    )

    class Meta:
        model = ClassificationDecisionTableNode
        fields = [
            "id",
            "graph",
            "node_name",
            "pre_python_code",
            "pre_input_map",
            "pre_output_variable_path",
            "post_python_code",
            "post_input_map",
            "post_output_variable_path",
            "default_llm_config",
            "default_next_node_id",
            "next_error_node_id",
            "created_at",
            "updated_at",
            "metadata",
            "condition_groups",
            "prompt_configs",
        ]

    def create(self, validated_data):
        condition_groups_data = validated_data.pop("condition_groups", None)
        prompt_configs_data = validated_data.pop("prompt_configs", None)
        pre_python_code_data = validated_data.pop("pre_python_code", None)
        post_python_code_data = validated_data.pop("post_python_code", None)

        pre_python_code = None
        if pre_python_code_data is not None:
            pre_python_code = PythonCode.objects.create(**pre_python_code_data)

        post_python_code = None
        if post_python_code_data is not None:
            post_python_code = PythonCode.objects.create(**post_python_code_data)

        node = ClassificationDecisionTableNode.objects.create(
            pre_python_code=pre_python_code,
            post_python_code=post_python_code,
            **validated_data,
        )

        sync_classification_decision_table_children(
            node,
            prompt_configs_data=prompt_configs_data,
            condition_groups_data=condition_groups_data,
        )

        return node

    def update(self, instance, validated_data):
        condition_groups_data = validated_data.pop("condition_groups", None)
        prompt_configs_data = validated_data.pop("prompt_configs", None)

        if "pre_python_code" in validated_data:
            pre_python_code_data = validated_data.pop("pre_python_code")

            if pre_python_code_data is None:
                instance.pre_python_code = None
            elif instance.pre_python_code is not None:
                python_code = instance.pre_python_code
                expected_hash = pre_python_code_data.pop("content_hash", None)
                if expected_hash is not None:
                    python_code._expected_hash = expected_hash
                for attr, value in pre_python_code_data.items():
                    setattr(python_code, attr, value)
                python_code.save()
            else:
                instance.pre_python_code = PythonCode.objects.create(
                    **pre_python_code_data
                )

        if "post_python_code" in validated_data:
            post_python_code_data = validated_data.pop("post_python_code")

            if post_python_code_data is None:
                instance.post_python_code = None
            elif instance.post_python_code is not None:
                python_code = instance.post_python_code
                expected_hash = post_python_code_data.pop("content_hash", None)
                if expected_hash is not None:
                    python_code._expected_hash = expected_hash
                for attr, value in post_python_code_data.items():
                    setattr(python_code, attr, value)
                python_code.save()
            else:
                instance.post_python_code = PythonCode.objects.create(
                    **post_python_code_data
                )

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        sync_classification_decision_table_children(
            instance,
            prompt_configs_data=prompt_configs_data,
            condition_groups_data=condition_groups_data,
        )

        return instance
