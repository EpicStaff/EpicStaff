from django.db import transaction
from rest_framework import serializers

from tables.exceptions import (
    BuiltInToolModificationError,
    PythonCodeToolConfigSerializerError,
)
from tables.models.label_models import Label
from tables.models.python_models import (
    PythonCode,
    PythonCodeResult,
    PythonCodeTool,
    PythonCodeToolConfig,
)
from tables.models.secret_models import Secret
from tables.serializers.base_serializer import ContentHashWritableMixin
from tables.serializers.org_scoped_fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgVisiblePrimaryKeyRelatedField,
    OrgScopedUniqueValidator,
    OrgScopedUniqueTogetherValidator,
    resolve_active_org_id,
)
from tables.serializers.utils.org_scoped_labels import (
    org_scoped_label_ids,
    set_org_scoped_labels,
)
from tables.services.copy_services.helpers import (
    apply_python_code_fields,
    create_python_code,
)
from tables.services.secrets.parse_code import parse_secret_names
from tables.validators.python_code_tool_config_validator import (
    PythonCodeToolConfigValidator,
)


class PythonCodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    libraries = serializers.ListField(
        child=serializers.CharField(),
        write_only=False,
        help_text="A list of library names.",
    )
    secret_ids = OrgScopedPrimaryKeyRelatedField(
        many=True,
        queryset=Secret.objects.all(),
        source="secrets",
        write_only=True,
        required=False,
        help_text=("Secrets this code is allowed to read."),
    )

    class Meta:
        model = PythonCode
        fields = [
            "id",
            "code",
            "entrypoint",
            "libraries",
            "global_kwargs",
            "secret_ids",
        ]
        read_only_fields = ["id"]
        extra_kwargs = {
            "code": {"allow_blank": True},
            "entrypoint": {"allow_blank": True},
        }

    def to_representation(self, instance):
        """Convert 'libraries' string to a list of strings for output."""
        representation = super().to_representation(instance)
        representation["libraries"] = (
            list(filter(None, instance.libraries.split(" ")))
            if instance.libraries
            else []
        )
        return representation

    def to_internal_value(self, data):
        """Convert 'libraries' list of strings to a space-separated string for storage."""
        internal_value = super().to_internal_value(data)
        libraries = data.get("libraries") or []
        if isinstance(libraries, list):
            internal_value["libraries"] = " ".join(libraries)
        return internal_value

    def validate(self, attrs):
        """Reject code that reads a secret this PythonCode did not declare."""
        attrs = super().validate(attrs)

        code = attrs.get("code")
        if code is None:
            code = getattr(self.instance, "code", "") or ""

        if "secrets" in attrs:
            declared = {secret.name for secret in attrs["secrets"]}
        elif self.instance is not None:
            declared = set(self.instance.secrets.values_list("name", flat=True))
        else:
            declared = set()

        parsed = parse_secret_names(code=code)
        undeclared = parsed - declared
        if undeclared:
            raise serializers.ValidationError(
                {
                    "secret_ids": self._undeclared_message(
                        undeclared=undeclared, declared=declared
                    )
                }
            )

        return attrs

    def _undeclared_message(self, *, undeclared: set[str], declared: set[str]) -> str:
        """Name what is wrong and list what would work."""
        # Sorted because `undeclared` is a set: unsorted, the same failure would
        # word itself differently between runs.
        calls = ", ".join(f'get_secret("{name}")' for name in sorted(undeclared))
        selected = ", ".join(sorted(declared)) or "none"
        available = ", ".join(self._available_secret_names()) or "none"
        return (
            f"Code calls {calls} but "
            f"{'those secrets are' if len(undeclared) > 1 else 'that secret is'} "
            f"not selected for this node. Selected: {selected}. "
            f"Available in this organization: {available}. "
            "Select them under Secrets, or remove the calls."
        )

    def _available_secret_names(self) -> list[str]:
        """The active org's secret names, or empty when they cannot be determined."""
        request = self.context.get("request")
        if request is None:
            return []
        try:
            org_id = resolve_active_org_id(request=request)
        except Exception:
            return []
        return sorted(
            Secret.objects.filter(org_id=org_id).values_list("name", flat=True)
        )


class PythonCodeToolSerializer(serializers.ModelSerializer):
    python_code = PythonCodeSerializer()
    built_in = serializers.ReadOnlyField()
    is_favorite = serializers.BooleanField(read_only=True, default=False)
    # Per-org unique name → clean 400 instead of a DB IntegrityError (500).
    name = serializers.CharField(
        validators=[
            OrgScopedUniqueValidator(
                queryset=PythonCodeTool.objects.all(),
                message="A tool with this name already exists.",
            )
        ]
    )
    labels = OrgScopedPrimaryKeyRelatedField(
        many=True,
        required=False,
        queryset=Label.objects.filter(scope=Label.Scope.TOOL),
    )

    class Meta:
        model = PythonCodeTool
        fields = [
            "id",
            "name",
            "description",
            "variables",
            "python_code",
            "is_favorite",
            "built_in",
            "use_storage",
            "labels",
        ]
        read_only_fields = ["id", "built_in"]

    def to_representation(self, instance):
        """Scope the serialized `labels` to the active org.

        `PythonCodeTool.labels` is a single M2M; a shared built-in tool
        (`org=None`) can carry attachments from several orgs on the same
        row. Without this, GET would leak another org's label ids on that
        shared row (EST-3773).
        """
        representation = super().to_representation(instance)
        representation["labels"] = org_scoped_label_ids(
            instance, self.context.get("request")
        )
        return representation

    def create(self, validated_data):
        labels = validated_data.pop("labels", [])
        python_code_data = validated_data.pop("python_code")
        with transaction.atomic():
            python_code = create_python_code(python_code_data=python_code_data)
            python_code_tool = PythonCodeTool.objects.create(
                python_code=python_code, **validated_data
            )
            set_org_scoped_labels(
                python_code_tool, labels, self.context.get("request")
            )
        return python_code_tool

    def update(self, instance, validated_data):
        labels = validated_data.pop("labels", None)
        python_code_data = validated_data.pop("python_code", None)

        if instance.built_in and (validated_data or python_code_data):
            raise BuiltInToolModificationError(
                "Built-in tools cannot be modified, except for labels"
            )

        with transaction.atomic():
            if python_code_data:
                apply_python_code_fields(
                    python_code=instance.python_code,
                    python_code_data=python_code_data,
                )

            for attr, value in validated_data.items():
                if attr != "built_in":
                    setattr(instance, attr, value)
            instance.save()

            if labels is not None:
                set_org_scoped_labels(instance, labels, self.context.get("request"))

        return instance


class PythonCodeToolConfigSerializer(serializers.ModelSerializer):
    # Org isolation (hybrid): built-in tools OR the caller's active-org custom ones.
    tool = OrgVisiblePrimaryKeyRelatedField(queryset=PythonCodeTool.objects.all())

    def __init__(self, *args, tool_config_validator=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.tool_config_validator = (
            tool_config_validator
            or PythonCodeToolConfigValidator(
                validate_null_fields=True,
                validate_missing_required_fields=True,
            )
        )

    class Meta:
        model = PythonCodeToolConfig
        fields = "__all__"
        read_only_fields = ["org", "created_by"]
        # Per-org unique (tool, name) → clean 400 instead of a DB IntegrityError.
        validators = [
            OrgScopedUniqueTogetherValidator(
                queryset=PythonCodeToolConfig.objects.all(),
                fields=["tool", "name"],
                message="A config with this name already exists for this tool.",
            )
        ]

    def validate(self, data: dict):
        name = data.get("name")
        tool = data.get("tool")
        configuration = data.get("configuration", dict())

        if name is None:
            raise PythonCodeToolConfigSerializerError(
                "Name for configuration is not provided."
            )
        if tool is None:
            raise PythonCodeToolConfigSerializerError("Tool is not provided.")
        if configuration is None:
            raise PythonCodeToolConfigSerializerError("Configuration is not provided.")

        try:
            validated_configuration = self.tool_config_validator.validate(
                name=name,
                tool=tool,
                configuration=configuration,
            )
            data["configuration"] = validated_configuration
        except serializers.ValidationError as e:
            raise PythonCodeToolConfigSerializerError(e.message)

        return data


class PythonCodeResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = PythonCodeResult
        fields = [
            "execution_id",
            "status",
            "result_data",
            "stderr",
            "stdout",
            "returncode",
            "created_at",
            "finished_at",
        ]
