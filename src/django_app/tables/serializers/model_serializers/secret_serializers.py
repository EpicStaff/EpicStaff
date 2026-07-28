from rest_framework import serializers

from tables.models import Secret
from tables.serializers.org_scoped_fields import OrgScopedUniqueTogetherValidator
from tables.services.secrets import secret_encryption


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
        secret = Secret(**validated_data)
        secret_encryption.encrypt(text=text).write_to(secret)
        secret.save()
        return secret

    def update(self, instance, validated_data):
        text = validated_data.pop("value", None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        if text is not None:
            secret_encryption.encrypt(text=text).write_to(instance)
        instance.save()
        return instance
