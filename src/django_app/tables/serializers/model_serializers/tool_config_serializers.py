from typing import Literal

from rest_framework import serializers

from tables.exceptions import ToolConfigSerializerError
from tables.models.crew_models import Tool, ToolConfig, ToolConfigField
from tables.validators.tool_config_validator import ToolConfigValidator, eval_any


class ToolConfigSerializer(serializers.ModelSerializer):
    def __init__(
        self, *args, tool_config_validator: ToolConfigValidator | None = None, **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.tool_config_validator = tool_config_validator or ToolConfigValidator(
            validate_null_fields=False, validate_missing_reqired_fields=False
        )

    class Meta:
        model = ToolConfig
        fields = "__all__"

    def validate(self, data: dict):
        name: str = data.get("name")
        tool: Tool = data.get("tool")
        configuration: dict = data.get("configuration", dict())

        if name is None:
            raise ToolConfigSerializerError("Name for configuration is not provided.")
        if tool is None:
            raise ToolConfigSerializerError("Tool is not provided.")
        if configuration is None:
            raise ToolConfigSerializerError("Configuration is not provided.")
        try:
            self.tool_config_validator.validate(
                name=name,
                tool=tool,
                configuration=configuration,
            )
        except serializers.ValidationError as e:
            raise ToolConfigSerializerError(e.message)

        return data

    # TODO: get rid of format parameter. Should use one as  pydantic.
    # using in: convert_configured_tool_to_pydantic()
    def to_representation(
        self, instance: ToolConfig, format: Literal["rest", "pydantic"] = "rest"
    ) -> dict:
        data = super().to_representation(instance)
        configuration: dict = data["configuration"]

        for key, value in configuration.items():
            tool_config_field: ToolConfigField = instance.get_tool_config_field(key)
            if tool_config_field.data_type == ToolConfigField.FieldType.ANY:
                # Get rid of ternar operator. Use only value["decoded_value"] (as pydantic)
                value = (
                    value["user_input"] if format == "rest" else value["decoded_value"]
                )

                configuration[key] = value

        data["is_completed"] = self.tool_config_validator.validate_is_completed(
            instance.tool, configuration
        )
        return data

    def to_internal_value(self, data: dict) -> dict:
        try:
            tool: Tool = Tool.objects.get(pk=data.get("tool"))
        except Tool.DoesNotExist:
            raise ToolConfigSerializerError(
                f"Tool with id: '{data.get('tool')}' does not exist", status_code=404
            )
        configuration: dict = data.get("configuration", dict())

        tool_config_fields = tool.get_tool_config_fields()

        for key, value in configuration.items():
            if key not in tool_config_fields:
                raise ToolConfigSerializerError(
                    f"Tool with id: '{tool.pk}' does not support field '{key}'. Available configuration fields: {[field for field in tool_config_fields.keys()]}",
                    status_code=404,
                )
            field = tool_config_fields.get(key)
            if field.data_type == ToolConfigField.FieldType.ANY:
                decoded_value = eval_any(key, value)

                # Problem with storring multivalued field in DB.
                # Potential solution: get rid of "user_input" and
                # dynamicaly calculate it from "decoded_value" if needed
                configuration[key] = {
                    "user_input": value,
                    "decoded_value": decoded_value,
                }

        data["configuration"] = configuration

        tool_config = super().to_internal_value(data)

        return tool_config
