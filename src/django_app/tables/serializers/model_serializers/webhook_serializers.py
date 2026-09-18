from rest_framework import serializers

from tables.models.webhook_models import WebhookTrigger


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = ["id", "path", "provider_type"]

    def validate(self, attrs):
        instance = self.instance or WebhookTrigger()
        for k, v in attrs.items():
            setattr(instance, k, v)
        try:
            instance.validate_unique()
        except serializers.ValidationError as e:
            raise serializers.ValidationError(
                e.message_dict if hasattr(e, "message_dict") else e.messages
            )
        return attrs
