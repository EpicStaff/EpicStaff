from rest_framework import serializers

from tables.models import Graph, DecisionTableNode, ConditionGroup, Condition


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


class DecisionTableNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )
    condition_groups = ConditionGroupImportSerializer(
        many=True, required=False, read_only=True
    )

    class Meta:
        model = DecisionTableNode
        exclude = ["created_at", "updated_at"]
