from rest_framework import serializers

from tables.models import (
    PythonCode,
    PythonCodeTool,
    PythonCodeToolConfig,
)
from tables.serializers.utils.description_sanitizer import validate_tool_description
from tables.serializers.utils.soft_delete_fields import ExcludeSoftDeleteFieldsMixin
from tables.validators.execution_timeout_validator import normalize_imported_execution_timeout


class PythonCodeImportSerializer(serializers.ModelSerializer):
    """Python code as it travels in an import/export file.

    Libraries are not here: they belong to the venv, which travels as its own
    `Venv` entry, and the code only names which one it runs in.
    """

    code = serializers.CharField(allow_blank=True)
    entrypoint = serializers.CharField(allow_blank=True, required=False)
    # A plain integer on purpose, not a related field: the value is the exporting
    # system's binding pk, so resolving it against this database would validate --
    # and could import -- another organization's environment. The strategies remap
    # it through the IDMapper before this serializer ever sees a local id.
    venv = serializers.IntegerField(source="venv_id", required=False, allow_null=True)

    class Meta:
        model = PythonCode
        exclude = ["id", "secrets"]

    def validate_execution_timeout(self, value: int) -> int:
        return normalize_imported_execution_timeout(value)

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
        exclude = [
            "labels",
            "created_by",
            "created_at",
            "updated_at",
        ]

    def validate_description(self, value: str) -> str:
        """See validate_tool_description: this text reaches the LLM tool schema verbatim."""
        return validate_tool_description(value)

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
