from loguru import logger
from rest_framework import serializers

from tables.models import (
    TelegramTriggerNode,
    TelegramTriggerNodeField,
    WebhookTrigger,
)
from tables.models.graph_models import TelegramTriggerNode, TelegramTriggerNodeField
from tables.models.webhook_models import WebhookTrigger
from tables.serializers.base_serializer import BaseGraphEntityMixin
from tables.serializers.base_serializers import WebhookTriggerNestedSerializer


class TelegramTriggerNodeFieldSerializer(serializers.ModelSerializer):
    class Meta:
        model = TelegramTriggerNodeField
        fields = [
            "id",
            "parent",
            "field_name",
            "variable_path",
        ]


class TelegramTriggerNodeSerializer(serializers.ModelSerializer):
    webhook_trigger = WebhookTriggerNestedSerializer(required=False, allow_null=True)
    fields = TelegramTriggerNodeFieldSerializer(many=True)

    class Meta(BaseGraphEntityMixin.Meta):
        model = TelegramTriggerNode
        fields = [
            "id",
            "node_name",
            "telegram_bot_api_key",
            "graph",
            "fields",
            "webhook_trigger",
        ] + BaseGraphEntityMixin.Meta.common_fields

    def create(self, validated_data):
        fields_data = validated_data.pop("fields", [])

        webhook_trigger_data = validated_data.pop("webhook_trigger", None)
        webhook_trigger_instance = None

        if webhook_trigger_data:
            path = webhook_trigger_data.get("path")
            ngrok_conf = webhook_trigger_data.get("ngrok_webhook_config")

            webhook_trigger_instance, created = WebhookTrigger.objects.get_or_create(
                path=path, ngrok_webhook_config=ngrok_conf
            )

        node = TelegramTriggerNode.objects.create(
            webhook_trigger=webhook_trigger_instance, **validated_data
        )
        for item in fields_data:
            TelegramTriggerNodeField.objects.create(telegram_trigger_node=node, **item)

        return node

    def update(self, instance, validated_data):
        fields_data = validated_data.pop("fields", None)

        if "webhook_trigger" in validated_data:
            webhook_trigger_data = validated_data.pop("webhook_trigger")

            if webhook_trigger_data:
                path = webhook_trigger_data.get("path")
                ngrok_conf = webhook_trigger_data.get("ngrok_webhook_config")

                webhook_trigger_instance, created = (
                    WebhookTrigger.objects.get_or_create(
                        path=path, ngrok_webhook_config=ngrok_conf
                    )
                )
                instance.webhook_trigger = webhook_trigger_instance
            else:
                instance.webhook_trigger = None

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()

        if fields_data is not None:
            instance.fields.all().delete()
            for item in fields_data:
                TelegramTriggerNodeField.objects.create(
                    telegram_trigger_node=instance, **item
                )

        return instance


class TelegramTriggerNodeDataFieldsSerializer(serializers.Serializer):
    data = serializers.JSONField()
