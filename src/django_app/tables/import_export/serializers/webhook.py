from rest_framework import serializers

from tables.models import WebhookTrigger


class WebhookTriggerImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = "__all__"
