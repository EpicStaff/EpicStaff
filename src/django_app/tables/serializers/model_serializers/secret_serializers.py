from django.utils.functional import SimpleLazyObject
from rest_framework import serializers

from tables.models import Secret
from tables.serializers.org_scoped_fields import OrgScopedUniqueTogetherValidator
from tables.services.secrets import secret_service, secret_usage_service


class SecretUsageCountListSerializer(serializers.ListSerializer):
    """Prepares one usage-count map for a list response; nothing else does."""

    def to_representation(self, data):
        org_id = self.context["view"].get_active_org_id()
        self.context["usage_counts"] = SimpleLazyObject(
            lambda: secret_usage_service.counts(org_id=org_id)
        )
        return super().to_representation(data)


class SecretSerializer(serializers.ModelSerializer):
    # Write-only and required: a Secret is created with its value and never
    # updated, so there is no "omit to keep the existing one" case.
    value = serializers.CharField(write_only=True)
    usage_count = serializers.SerializerMethodField()

    class Meta:
        model = Secret
        list_serializer_class = SecretUsageCountListSerializer
        fields = [
            "id",
            "name",
            "value",
            "tail",
            "metadata",
            "org",
            "created_by",
            "created_at",
            "updated_at",
            "usage_count",
        ]
        read_only_fields = [
            "id",
            "tail",
            "org",
            "created_by",
            "created_at",
            "updated_at",
        ]
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=Secret.objects.filter(system=False),
                fields=["name"],
                message="A secret with this name already exists in this organization.",
            )
        ]

    def create(self, validated_data):
        text = validated_data.pop("value")
        return secret_service.create(text=text, **validated_data)

    def get_usage_count(self, secret) -> int:
        """Distinct resources referencing this secret."""
        counts = self.context.get("usage_counts")
        if counts is not None:
            return counts[secret.pk]
        return secret_usage_service.count_for(secret=secret)
