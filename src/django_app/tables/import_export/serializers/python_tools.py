from rest_framework import serializers

from tables.models import (
    PythonCode,
    PythonCodeTool,
    PythonCodeToolConfig,
)


class PythonCodeImportSerializer(serializers.ModelSerializer):
    libraries = serializers.CharField(allow_blank=True)
    entrypoint = serializers.CharField(allow_blank=True, required=False)

    class Meta:
        model = PythonCode
        exclude = ["id"]

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
        exclude = ["id", "tool"]


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
        exclude = ["favorite"]
