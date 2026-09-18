from rest_framework import serializers

from tables.models import Graph, WebhookTriggerNode, PythonCode, WebhookTrigger
from tables.import_export.serializers.python_tools import PythonCodeImportSerializer


class WebhookTriggerNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )
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

    class Meta:
        model = WebhookTriggerNode
        exclude = ["created_at", "updated_at"]
