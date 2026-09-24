from rest_framework import serializers

from tables.models import WebhookTrigger
from tables.services.webhook_trigger_service import validate_path_uniqueness


class WebhookTriggerImportSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = ["id", "path", "provider_type"]

    def validate(self, attrs):
        validate_path_uniqueness(
            path=attrs.get("path"),
            exclude_pk=self.instance.pk if self.instance else None,
        )
        return attrs
