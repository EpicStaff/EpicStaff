import json

from rest_framework import serializers


class PluginInspectRequestSerializer(serializers.Serializer):
    file = serializers.FileField()


class PluginInstallRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    # A JSON object string, slot name -> value: multipart forms carry no nested data.
    secrets = serializers.CharField(required=False, default="{}", trim_whitespace=False)

    def validate_secrets(self, value: str) -> dict[str, str]:
        try:
            secrets = json.loads(value)
        except json.JSONDecodeError as exc:
            raise serializers.ValidationError("secrets must be a JSON object.") from exc
        if not isinstance(secrets, dict) or not all(
            isinstance(name, str) and isinstance(secret, str) for name, secret in secrets.items()
        ):
            raise serializers.ValidationError(
                "secrets must be a JSON object mapping slot names to string values."
            )
        return secrets


class PluginSecretsRequestSerializer(serializers.Serializer):
    # Values are checked against the plugin's slots by the service, so that every
    # problem comes back in the `invalid_plugin_secrets` shape.
    secrets = serializers.DictField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False)
    )
    retry_indexing = serializers.BooleanField(required=False, default=False)


class PluginDevUiRequestSerializer(serializers.Serializer):
    # Checked by PluginDevUiService, which owns the rule for an acceptable dev URL.
    url = serializers.CharField(trim_whitespace=False)
