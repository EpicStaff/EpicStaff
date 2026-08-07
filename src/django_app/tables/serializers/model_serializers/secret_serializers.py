from rest_framework import serializers

from tables.models import Secret
from tables.serializers.org_scoped_fields import OrgScopedUniqueTogetherValidator
from tables.services.secrets import secret_service


class SecretSerializer(serializers.ModelSerializer):
    # Write-only and required: a Secret is created with its value and never
    # updated, so there is no "omit to keep the existing one" case.
    value = serializers.CharField(write_only=True)
    usage_count = serializers.SerializerMethodField()

    class Meta:
        model = Secret
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

    def get_usage_count(self, secret) -> int:
        """Distinct resources referencing this secret.

        Indexed directly rather than .get(pk, 0): counts() enumerates every secret in
        the org, so an absent key means the service is broken, and a KeyError says so
        loudly instead of rendering a broken sweep as "unused" — the dangerous
        direction for a deletion guard.
        """

        return self.context["usage_counts"][secret.pk]
