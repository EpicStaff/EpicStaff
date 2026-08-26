from django.db import transaction

from tables.models.secret_models import Secret
from tables.models.webhook_models import (
    LOCAL_ONLY_PROVIDERS,
    LocalhostWebhookConfig,
    NgrokWebhookConfig,
    ProviderType,
    WebhookTrigger,
)
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    resolve_active_org_id,
)
from rest_framework import serializers
from utils.logger import logger


class NgrokConfigInlineSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    auth_token_secret_id = OrgScopedPrimaryKeyRelatedField(
        queryset=Secret.objects.all(),
        source="auth_token_secret",
        required=False,
        allow_null=True,
    )
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


class WebhookTriggerNestedSerializer(serializers.ModelSerializer):
    provider_type = serializers.ChoiceField(
        choices=ProviderType.choices, required=False, allow_null=True
    )
    ngrok_config = NgrokConfigInlineSerializer(required=False, allow_null=True)
    localhost_config = LocalhostConfigInlineSerializer(required=False, allow_null=True)

    @transaction.atomic
    def create(self, validated_data):
        # A true create — always inserts a new row. `validate()` already
        # rejects an exact (path, provider_type) duplicate before we get
        # here, so two different providers sharing the same `path` legally
        # create two separate WebhookTrigger rows (unique_together allows
        # it). No existing-row lookup/merge/config-deletion here — that
        # get-or-create behavior used to hijack another provider's row on a
        # path collision (EST-3625).
        request = self.context.get("request")
        org_id = resolve_active_org_id(request) if request is not None else None
        if org_id is None:
            raise serializers.ValidationError(
                "Organization context is required to create a webhook trigger."
            )

        provider_type = validated_data.get("provider_type")
        trigger = WebhookTrigger.objects.create(
            path=validated_data.get("path"),
            provider_type=provider_type,
            org_id=org_id,
            created_by=getattr(request, "user", None),
        )

        if provider_type == ProviderType.NGROK:
            ngrok_data = validated_data.get("ngrok_config")
            if ngrok_data:
                NgrokWebhookConfig.objects.create(trigger=trigger, **ngrok_data)
        elif provider_type == ProviderType.LOCALHOST:
            localhost_data = validated_data.get("localhost_config")
            if localhost_data:
                LocalhostWebhookConfig.objects.create(trigger=trigger, **localhost_data)

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

            base_url = WebhookTriggerService().get_tunnel_url_for_trigger(instance)
            rep["live_url"] = (
                f"{base_url.rstrip('/')}/webhooks/{instance.path}"
                if base_url is not None
                else None
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
