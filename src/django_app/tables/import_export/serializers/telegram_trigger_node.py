from rest_framework import serializers

from tables.models import Graph, TelegramTriggerNode, TelegramTriggerNodeField


class TelegramTriggerNodeFieldImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramTriggerNodeField
        exclude = ["telegram_trigger_node"]


class TelegramTriggerNodeImportSerializer(serializers.ModelSerializer):
    node_type = serializers.CharField(required=False)
    graph = serializers.PrimaryKeyRelatedField(
        queryset=Graph.objects.all(), write_only=True
    )
    fields = TelegramTriggerNodeFieldImportSerializer(many=True, read_only=True)

    class Meta:
        model = TelegramTriggerNode
        exclude = ["created_at", "updated_at", "telegram_bot_api_key"]
