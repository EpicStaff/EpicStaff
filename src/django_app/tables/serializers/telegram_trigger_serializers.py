from rest_framework import serializers
from tables.models.graph_models import TelegramTriggerNode, TelegramTriggerNodeField
from tables.serializers.base_serializer import BaseGraphEntityMixin


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
    fields = TelegramTriggerNodeFieldSerializer(many=True)

    class Meta(BaseGraphEntityMixin.Meta):
        model = TelegramTriggerNode
        fields = [
            "id",
            "node_name",
            "telegram_bot_api_key",
            "graph",
            "fields",
        ] + BaseGraphEntityMixin.Meta.common_fields

    def create(self, validated_data):
        fields_data = validated_data.pop("fields", [])

        node = TelegramTriggerNode.objects.create(**validated_data)

        for item in fields_data:
            TelegramTriggerNodeField.objects.create(telegram_trigger_node=node, **item)

        return node

    def update(self, instance, validated_data):
        fields_data = validated_data.pop("fields", None)

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
