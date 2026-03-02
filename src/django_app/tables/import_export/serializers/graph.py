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
    PythonCode,
    WebhookTrigger,
    ConditionGroup,
    Condition,
    SubGraphNode,
)
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer


class BaseNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )

    class Meta:
        model = None
        exclude = ["created_at", "updated_at", "content_hash"]


class StartNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = StartNode
        exclude = ["created_at", "updated_at", "content_hash"]


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
    )

    class Meta(BaseNodeImportSerializer.Meta):
        model = WebhookTriggerNode
        exclude = ["created_at", "updated_at", "content_hash"]


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
        exclude = ["created_at", "updated_at", "content_hash"]


class TelegramTriggerNodeFieldImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramTriggerNodeField
        exclude = ["telegram_trigger_node"]


class TelegramTriggerNodeImportSerializer(BaseNodeImportSerializer):
    fields = TelegramTriggerNodeFieldImportSerializer(many=True, read_only=True)

    class Meta:
        model = TelegramTriggerNode
        exclude = ["created_at", "updated_at", "content_hash", "telegram_bot_api_key"]


class PythonNodeImportSerializer(BaseNodeImportSerializer):
    python_code = PythonCodeImportSerializer(read_only=True)
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        write_only=True,
    )

    class Meta(BaseNodeImportSerializer.Meta):
        model = PythonNode
        exclude = ["created_at", "updated_at", "content_hash"]


class EndNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = EndNode
        exclude = ["created_at", "updated_at", "content_hash"]


class FileExtractorNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = FileExtractorNode
        exclude = ["created_at", "updated_at", "content_hash"]


class AudioTranscriptionNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = AudioTranscriptionNode
        exclude = ["created_at", "updated_at", "content_hash"]


class LLMNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = LLMNode
        exclude = ["created_at", "updated_at", "content_hash"]


class CrewNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = CrewNode
        exclude = ["created_at", "updated_at", "content_hash"]


class SubgraphNodeImportSerializer(BaseNodeImportSerializer):
    class Meta(BaseNodeImportSerializer.Meta):
        model = SubGraphNode
        exclude = ["created_at", "updated_at", "content_hash"]


class EdgeImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Edge
        exclude = ["created_at", "updated_at", "content_hash"]


class GraphImportSerializer(serializers.ModelSerializer):
    edge_list = EdgeImportSerializer(many=True, read_only=True)
    nodes = serializers.JSONField(required=False)

    class Meta:
        model = Graph
        exclude = ["tags"]
