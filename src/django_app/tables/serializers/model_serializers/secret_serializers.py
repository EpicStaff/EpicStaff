from rest_framework import serializers

from tables.models import Secret
from tables.serializers.org_scoped_fields import OrgScopedUniqueTogetherValidator
from tables.services.secrets import secret_service


class SecretSerializer(serializers.ModelSerializer):
    value = serializers.CharField(write_only=True, required=False)

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

    def validate(self, attrs):
        if self.instance is None and "value" not in attrs:
            raise serializers.ValidationError(
                {"value": "This field is required when creating a secret."}
            )
        return attrs

    def create(self, validated_data):
        text = validated_data.pop("value")
        return secret_service.create(text=text, **validated_data)

    def update(self, instance, validated_data):
        text = validated_data.pop("value", None)
        return secret_service.update(instance=instance, text=text, **validated_data)
