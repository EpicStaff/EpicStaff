from rest_framework import serializers

from tables.models import (
    PythonCode,
    PythonCodeTool,
    PythonCodeToolConfig,
)
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


class PythonCodeToolConfigImportSerializer(serializers.ModelSerializer):
    tool_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCodeTool.objects.all(),
        source="tool",
        write_only=True,
    )

    class Meta:
        model = PythonCodeToolConfig
        exclude = ["id", "tool", "created_by"]


class PythonCodeToolImportSerializer(serializers.ModelSerializer):
    python_code = PythonCodeImportSerializer(required=False, read_only=True)
    python_code_id = serializers.PrimaryKeyRelatedField(
        queryset=PythonCode.objects.all(),
        source="python_code",
        write_only=True,
    )
    python_code_tool_config = PythonCodeToolConfigImportSerializer(
        source="pythoncodetoolconfig_set", many=True, read_only=True
    )

    class Meta:
        model = PythonCodeTool
        exclude = ["labels", "created_by"]
