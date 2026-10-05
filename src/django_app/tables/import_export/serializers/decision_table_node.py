from rest_framework import serializers

from tables.models import Condition, ConditionGroup, DecisionTableNode, Graph
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin


class ConditionImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    condition_group = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Condition
        fields = "__all__"


class ConditionGroupImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
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


class DecisionTableNodeImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(queryset=Graph.objects.all(), write_only=True)
    condition_groups = ConditionGroupImportSerializer(many=True, required=False, read_only=True)

    class Meta:
        model = DecisionTableNode
        exclude = ["created_at", "updated_at"]
