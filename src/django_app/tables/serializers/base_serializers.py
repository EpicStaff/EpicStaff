from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.serializers.utils.mixins import WebhookCreationMixin
from rest_framework import serializers
from utils.logger import logger


class NgrokConfigInlineSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    auth_token = serializers.CharField(max_length=255, write_only=True)
    domain = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )
    region = serializers.ChoiceField(
        choices=NgrokWebhookConfig.Region.choices,
        default=NgrokWebhookConfig.Region.EU,
    )


class LocalhostConfigInlineSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    domain = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )


class WebhookTriggerNestedSerializer(WebhookCreationMixin, serializers.ModelSerializer):
    provider_type = serializers.ChoiceField(
        choices=ProviderType.choices, required=False, allow_null=True
    )
    ngrok_config = NgrokConfigInlineSerializer(required=False, allow_null=True)
    localhost_config = LocalhostConfigInlineSerializer(required=False, allow_null=True)

    def create(self, validated_data):
        trigger, _ = self._get_or_create_webhook_trigger(validated_data)
        return trigger

    def update(self, instance, validated_data):
        # Update the existing trigger in place (no get_or_create) so a
        # provider_type change re-points the same row instead of spawning
        # a new WebhookTrigger.
        old_provider = instance.provider_type
        new_provider = validated_data.get("provider_type", instance.provider_type)
        instance.path = validated_data.get("path", instance.path)
        instance.provider_type = new_provider
        instance.save()

        ngrok_data = validated_data.get("ngrok_config")
        localhost_data = validated_data.get("localhost_config")

        if new_provider != old_provider:
            if old_provider == ProviderType.NGROK:
                NgrokWebhookConfig.objects.filter(trigger=instance).delete()
                logger.info(
                    "Deleted NgrokWebhookConfig for trigger pk=%s (provider_type=%s)",
                    instance.pk,
                    old_provider,
                )
            elif old_provider == ProviderType.LOCALHOST:
                LocalhostWebhookConfig.objects.filter(trigger=instance).delete()
                logger.info(
                    "Deleted LocalhostWebhookConfig for trigger pk=%s (provider_type=%s)",
                    instance.pk,
                    old_provider,
                )

        if new_provider == ProviderType.NGROK and ngrok_data:
            NgrokWebhookConfig.objects.update_or_create(
                trigger=instance, defaults=ngrok_data
            )
        elif new_provider == ProviderType.LOCALHOST and localhost_data:
            LocalhostWebhookConfig.objects.update_or_create(
                trigger=instance, defaults=localhost_data
            )

        return instance

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        ngrok = getattr(instance, "ngrok", None)
        localhost = getattr(instance, "localhost", None)
        rep["ngrok_config"] = NgrokConfigInlineSerializer(ngrok).data if ngrok else None
        rep["localhost_config"] = (
            LocalhostConfigInlineSerializer(localhost).data if localhost else None
        )
        try:
            from tables.services.webhook_trigger_service import WebhookTriggerService

            rep["live_url"] = WebhookTriggerService().get_tunnel_url_for_trigger(
                instance
            )
        except Exception:
            logger.exception(
                "Failed to resolve live_url for WebhookTrigger id=%s", instance.pk
            )
            rep["live_url"] = None
        return rep

    def validate(self, data):
        provider_type = data.get("provider_type")
        ngrok = data.get("ngrok_config")
        localhost = data.get("localhost_config")

        path = data.get("path", self.instance.path if self.instance else None)
        lookup_provider_type = data.get(
            "provider_type",
            self.instance.provider_type if self.instance else None,
        )
        queryset = WebhookTrigger.objects.filter(
            path=path, provider_type=lookup_provider_type
        )
        if self.instance:
            queryset = queryset.exclude(id=self.instance.id)
        if queryset.exists():
            raise serializers.ValidationError(
                "A WebhookTrigger with this path and provider type already exists."
            )

        if ngrok and localhost:
            raise serializers.ValidationError(
                "A WebhookTrigger can only be linked to one config: either ngrok or localhost, not both."
            )
        if provider_type == ProviderType.NGROK and not ngrok:
            raise serializers.ValidationError(
                "ngrok_config is required when provider_type is 'ngrok'."
            )
        if provider_type == ProviderType.LOCALHOST and not localhost:
            raise serializers.ValidationError(
                "localhost_config is required when provider_type is 'localhost'."
            )

        return data

    class Meta:
        model = WebhookTrigger
        fields = ["id", "path", "provider_type", "ngrok_config", "localhost_config"]
        extra_kwargs = {"path": {"validators": []}}
        validators = []
