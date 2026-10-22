from rest_framework import serializers
from tables.models.webhook_models import WebhookTrigger
from tables.services.webhook_trigger_service import validate_path_uniqueness


class WebhookTriggerSerializer(serializers.ModelSerializer):
    class Meta:
        model = WebhookTrigger
        fields = ["id", "path", "provider_type"]

    def validate(self, attrs):
        path = attrs.get("path", getattr(self.instance, "path", None))
        validate_path_uniqueness(
            path=path,
            exclude_pk=self.instance.pk if self.instance else None,
        )
        return attrs


class WebhookTriggerFlowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()


class WebhookTriggerFlowsSerializer(serializers.Serializer):
    """Read-only shape of the webhook trigger's flows action."""

    flow_count = serializers.IntegerField(
        help_text="How many flows hold a live trigger node on this trigger."
    )
    flows = WebhookTriggerFlowSerializer(
        many=True,
        help_text=(
            "The first of those flows by name, then id; empty when the caller cannot read flows."
        ),
    )
