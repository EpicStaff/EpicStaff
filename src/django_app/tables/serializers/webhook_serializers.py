from tables.models.webhook_models import WebhookTrigger
from tables.models.python_models import PythonCode
from tables.models.graph_models import WebhookTriggerNode
from tables.serializers.model_serializers import PythonCodeSerializer
from rest_framework import serializers


class WebhookTriggerNodeSerializer(serializers.ModelSerializer):
    python_code = PythonCodeSerializer()
    webhook_trigger_path = serializers.CharField(
        required=False, allow_blank=True
    )
    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["webhook_trigger_path"] = (
            instance.webhook_trigger.path if instance.webhook_trigger else None
        )
        return data

    class Meta:
        model = WebhookTriggerNode
        exclude = ["webhook_trigger"]

    def create(self, validated_data):
        python_code_data = validated_data.pop("python_code")
        python_code = PythonCode.objects.create(**python_code_data)

        webhook_trigger_path = validated_data.pop("webhook_trigger_path", "").strip()
        if not webhook_trigger_path:
            webhook_trigger_path = "default"

        webhook_trigger, _ = WebhookTrigger.objects.get_or_create(
            path=webhook_trigger_path
        )

        webhook_trigger_node = WebhookTriggerNode.objects.create(
            python_code=python_code,
            webhook_trigger=webhook_trigger,
            **validated_data,
        )
        return webhook_trigger_node

    def update(self, instance, validated_data):
        python_code_data = validated_data.pop("python_code", None)
        if python_code_data:
            python_code = instance.python_code
            for attr, value in python_code_data.items():
                setattr(python_code, attr, value)
            python_code.save()

        webhook_trigger_path = validated_data.pop("webhook_trigger_path", None)
        if webhook_trigger_path is not None:
            webhook_trigger_path = webhook_trigger_path.strip() or "default"
            webhook_trigger, _ = WebhookTrigger.objects.get_or_create(
                path=webhook_trigger_path
            )
            instance.webhook_trigger = webhook_trigger

        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance

    def partial_update(self, instance, validated_data):
        return self.update(instance, validated_data)


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = "__all__"
