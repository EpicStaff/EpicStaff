from rest_framework import serializers

from tables.exceptions import (
    BuiltInToolModificationError,
    PythonCodeToolConfigSerializerError,
)
from tables.models.python_models import (
    PythonCode,
    PythonCodeResult,
    PythonCodeTool,
    PythonCodeToolConfig,
)
from tables.serializers.base_serializer import ContentHashWritableMixin
from tables.validators.python_code_tool_config_validator import (
    PythonCodeToolConfigValidator,
)


class PythonCodeSerializer(ContentHashWritableMixin, serializers.ModelSerializer):
    libraries = serializers.ListField(
        child=serializers.CharField(),
        write_only=False,
        help_text="A list of library names.",
    )

    class Meta:
        model = PythonCode
        fields = "__all__"
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


class PythonCodeToolSerializer(serializers.ModelSerializer):
    python_code = PythonCodeSerializer()
    built_in = serializers.ReadOnlyField()

    class Meta:
        model = PythonCodeTool
        fields = [
            "id",
            "name",
            "description",
            "variables",
            "python_code",
            "favorite",
            "built_in",
            "use_storage",
        ]
        read_only_fields = ["id", "built_in"]

    def create(self, validated_data):
        python_code_data = validated_data.pop("python_code")
        python_code = PythonCode.objects.create(**python_code_data)
        python_code_tool = PythonCodeTool.objects.create(
            python_code=python_code, **validated_data
        )
        return python_code_tool

    def update(self, instance, validated_data):
        if instance.built_in:
            raise BuiltInToolModificationError()

        python_code_data = validated_data.pop("python_code", None)

        if python_code_data:
            python_code = instance.python_code
            for attr, value in python_code_data.items():
                setattr(python_code, attr, value)
            python_code.save()

        for attr, value in validated_data.items():
            if attr != "built_in":
                setattr(instance, attr, value)
        instance.save()

        return instance


class PythonCodeToolConfigSerializer(serializers.ModelSerializer):
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
        fields = "__all__"
