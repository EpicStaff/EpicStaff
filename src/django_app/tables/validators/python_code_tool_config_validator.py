from tables.exceptions import PythonCodeToolConfigSerializerError
from tables.models.python_models import PythonCodeTool

_USER_INPUT_TYPES = ("user_input", "mixed")
_AGENT_INPUT_TYPE = "agent_input"

_PRIMITIVE_TYPE_CAST = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "any": lambda v: v,
}


class PythonCodeToolConfigValidator:
    def __init__(
        self, validate_null_fields=True, validate_missing_required_fields=True
    ):
        self.validate_null_fields = validate_null_fields
        self.validate_missing_required_fields = validate_missing_required_fields

    def validate(self, name, tool: PythonCodeTool, configuration: dict):
        if not isinstance(configuration, dict):
            raise PythonCodeToolConfigSerializerError(
                "Field configuration must be an object"
            )

        agent_names = {
            v["name"]
            for v in tool.variables
            if v.get("input_type") == _AGENT_INPUT_TYPE
        }
        for key in configuration:
            if key in agent_names:
                raise PythonCodeToolConfigSerializerError(
                    f"Field '{key}' is set by the agent and cannot be configured by the user"
                )

        validated = {}
        for var in tool.variables:
            if var.get("input_type") not in _USER_INPUT_TYPES:
                continue

            field_name = var["name"]
            value = configuration.get(field_name)

            if (
                value is None
                and var.get("required")
                and self.validate_missing_required_fields
            ):
                raise PythonCodeToolConfigSerializerError(
                    f"Field '{field_name}' is required"
                )

            if value is not None:
                value = self._cast_var(value, var)

            validated[field_name] = value

        return validated

    def _cast_var(self, value, var: dict):
        var_type = var.get("type", "string")
        if var_type in ("object", "obj"):
            return self._cast_object(value, var.get("properties", {}), var.get("required_properties", []))
        if var_type in ("array", "list"):
            return self._cast_array(value, var.get("items", {}))
        return self._cast_primitive(value, var_type)

    def _cast_object(self, value, properties: dict, required_properties: list) -> dict:
        if not isinstance(value, dict):
            raise PythonCodeToolConfigSerializerError(
                f"Expected an object, got '{type(value).__name__}'"
            )
        result = {}
        for prop_name, prop_schema in properties.items():
            prop_value = value.get(prop_name)
            if prop_value is None and prop_name in required_properties:
                raise PythonCodeToolConfigSerializerError(
                    f"Field '{prop_name}' is required"
                )
            if prop_value is not None:
                prop_value = self._cast_var(prop_value, {"name": prop_name, **prop_schema})
            result[prop_name] = prop_value
        return result

    def _cast_array(self, value, items_schema: dict) -> list:
        if not isinstance(value, list):
            raise PythonCodeToolConfigSerializerError(
                f"Expected an array, got '{type(value).__name__}'"
            )
        return [self._cast_var(item, {"name": "item", **items_schema}) for item in value]

    def _cast_primitive(self, value, var_type: str):
        cast_fn = _PRIMITIVE_TYPE_CAST.get(var_type, lambda v: v)
        try:
            return cast_fn(value)
        except (ValueError, TypeError):
            raise PythonCodeToolConfigSerializerError(
                f"Error casting value '{value}' into '{var_type}'"
            )
