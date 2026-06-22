import re

from typing import Any, Collection, Optional

from pydantic import BaseModel as PydanticModel, create_model, Field
from pydantic.fields import FieldInfo

from src.shared.models import (
    variable_adapter,
    VariableTypeInput,
    VariableType,
    Variable,
    ObjectVariable,
    ArrayVariable,
)

__all__ = ["ArgsSchemaFactory"]


class ArgsSchemaFactory:
    """
    Builds a Pydantic args_schema model dynamically from a variable list.
    """

    @classmethod
    def create(
        cls,
        tool_name: str,
        variables: Collection[dict],
        resolved_variables: Optional[Collection[str]] = None,
    ) -> type[PydanticModel]:
        resolved_variables = resolved_variables or set()
        model_fields = cls._build_model_fields(variables, resolved_variables)
        tool_model_name = cls._normalize_model_name(tool_name)
        model_name = "ArgsSchemaOf" + tool_model_name
        return create_model(
            model_name,
            __doc__=f"Input schema for {tool_model_name}",
            __base__=PydanticModel,
            **model_fields,
        )

    @staticmethod
    def _normalize_model_name(value: str, *, pattern=re.compile(r"[A-Za-z]+")) -> str:
        return "".join(s.capitalize() for s in pattern.findall(value))

    @classmethod
    def _build_model_fields(
        cls,
        variables: Collection[dict],
        resolved_variables: Collection[str],
    ) -> dict[str, tuple[type, FieldInfo]]:
        """Build the field mapping for `pydantic.create_model` from the variable list."""
        fields = {}
        for var in variables:
            var = variable_adapter.validate_python(var)
            if var.input_type not in (VariableTypeInput.AGENT, VariableTypeInput.MIXED):
                continue

            if var.name in resolved_variables:
                continue

            default = cls._get_default(var.default_value, var.required)
            description = cls._compose_description(var.description, var)
            fields[var.name] = (
                var.python_type,
                Field(default=default, description=description),
            )
        return fields

    @staticmethod
    def _get_default(default_value: Any, required: bool) -> Any:
        if default_value is None:
            if required:
                return ...
            else:
                return None

        return default_value

    @staticmethod
    def _compose_description(description: str, variable: Variable):
        """Compose the agent-facing description for a single args_schema field."""
        composed_description = description
        if variable.type == VariableType.OBJECT:
            assert isinstance(variable, ObjectVariable)
            composed_description += (
                f" Expected JSON object with fields: {variable.properties}."
                f" Required fields: {variable.required_properties}."
            )

        elif variable.type == VariableType.ARRAY:
            assert isinstance(variable, ArrayVariable)
            composed_description += f" Expected JSON array of {variable.item}."

        if variable.default_value is not None:
            if description:
                composed_description += (
                    " If you cannot determine an appropriate value,"
                    f" from the given context, use `{variable.default_value}` as the default."
                )
            else:
                composed_description = (
                    f"Use `{variable.default_value}` as the default value."
                )

        return composed_description
