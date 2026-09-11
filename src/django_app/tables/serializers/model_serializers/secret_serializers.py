from django.utils.functional import SimpleLazyObject
from rest_framework import serializers

from tables.models import Secret
from tables.serializers.org_scoped_fields import (
    OrgScopedUniqueTogetherValidator,
    resolve_active_org_id,
)
from tables.services.rbac.permission_resolver import PermissionResolver
from tables.services.secrets import secret_service, secret_usage_service

_permission_resolver = PermissionResolver()


def _effective_for(*, context):
    """The requesting user's resolved permissions in the active org."""
    request = context["request"]
    return _permission_resolver.resolve(
        user=request.user, org_id=resolve_active_org_id(request)
    )


class SecretUsageCountListSerializer(serializers.ListSerializer):
    """Prepares one usage-count map for a list response; nothing else does."""

    def to_representation(self, data):
        org_id = self.context["view"].get_active_org_id()
        effective = _effective_for(context=self.context)
        self.context["usage_counts"] = SimpleLazyObject(
            lambda: secret_usage_service.counts(org_id=org_id, effective=effective)
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
                queryset=Secret.objects.all(),
                fields=["name"],
                message="A secret with this name already exists in this organization.",
            )
        ]

    def create(self, validated_data):
        text = validated_data.pop("value")
        return secret_service.create(text=text, **validated_data)

    def get_usage_count(self, secret) -> dict:
        """Readable and hidden counts of resources referencing this secret."""
        counts = self.context.get("usage_counts")
        if counts is None:
            counts = {
                secret.pk: secret_usage_service.count_for(
                    secret=secret, effective=_effective_for(context=self.context)
                )
            }
        return {
            "readable": counts[secret.pk].readable,
            "hidden": counts[secret.pk].hidden,
        }


class SecretNameSerializer(serializers.ModelSerializer):
    """A secret's identity without any part of its value."""

    class Meta:
        model = Secret
        fields = ["id", "name"]
