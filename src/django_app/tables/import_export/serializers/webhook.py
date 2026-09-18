from rest_framework import serializers

from tables.models import WebhookTrigger


class WebhookTriggerImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = ["id", "path", "provider_type"]
