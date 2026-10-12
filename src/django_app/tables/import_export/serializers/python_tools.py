from rest_framework import serializers

from tables.models import (
    PythonCode,
    PythonCodeTool,
    PythonCodeToolConfig,
)
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin
from tables.validators.python_libraries_validator import validate_python_library_spec


class PythonCodeImportSerializer(serializers.ModelSerializer):
    code = serializers.CharField(allow_blank=True)
    libraries = serializers.CharField(allow_blank=True)
    entrypoint = serializers.CharField(allow_blank=True, required=False)

    class Meta:
        model = PythonCode
        exclude = ["id", "secrets"]

    def validate_libraries(self, value: str) -> str:
        """Apply the runtime rule to every entry of the space-separated string.

        An import file is untrusted input, and the sandbox runs `pip install` on
        each entry, so a VCS URL, a direct `name @ url` reference or a file path
        must be rejected here exactly as `PythonCodeSerializer` rejects it.
        """
        for entry in value.split():
            validate_python_library_spec(entry)
        return value

    def to_internal_value(self, data):
        result = super().to_internal_value(data)
        if not result.get("entrypoint"):
            result["entrypoint"] = "main"
        return result


class PythonCodeToolConfigImportSerializer(
    ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer
):
    tool_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCodeTool.objects.all(),
        source="tool",
        write_only=True,
    )

    class Meta:
        model = PythonCodeToolConfig
        exclude = ["id", "tool", "created_by"]
        # The source org means nothing to the importer, which stamps its own.
        # Write-only rather than excluded so the (org, tool, name)
        # unique-together validator still runs on import.
        extra_kwargs = {"org": {"write_only": True}}


class PythonCodeToolImportSerializer(ExcludeSoftDeleteFieldsMixin, serializers.ModelSerializer):
    python_code = PythonCodeImportSerializer(required=False, read_only=True)
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        write_only=True,
    )
    python_code_tool_config = serializers.SerializerMethodField()

    class Meta:
        model = PythonCodeTool
        exclude = ["labels", "created_by"]

    def get_python_code_tool_config(self, instance: PythonCodeTool) -> list[dict]:
        """Serialize only the exporting organization's configs of this tool.

        A built-in tool is one row shared by every organization, and each
        organization stores its own configs (which hold credentials) against it,
        so the reverse relation spans tenants. The org comes from the
        ``org_id`` serializer context; without it no config is emitted.
        """
        org_id = self.context.get("org_id")
        if org_id is None:
            return []
        configs = PythonCodeToolConfig.objects.filter(tool=instance, org_id=org_id).order_by("id")
        return PythonCodeToolConfigImportSerializer(configs, many=True).data
