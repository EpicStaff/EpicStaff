from typing import Any, Iterable
from tables.models import (
    Tool,
    ToolConfig,
    ToolConfigField,
    Agent,
    LLMConfig,
    EmbeddingConfig,
    Crew,
)
from django.core.exceptions import ValidationError
from loguru import logger
from ast import literal_eval


def eval_any(key: str, value: str) -> Any:
    try:
        decoded_value = literal_eval(value)
    except Exception:
        message = f"{key} validation error.\nReason: {value} faild to decode"
        raise ValidationError(message)

    return decoded_value


class ToolConfigValidator:

    @staticmethod
    def llm_config_validation(key: str, llm_config_id: int):
        try:
            LLMConfig.objects.get(pk=llm_config_id)
        except LLMConfig.DoesNotExist:
            message = f"'{key}' validation error.Reason: LLM config with id {llm_config_id} does not exists"

            raise ValidationError(message)

    @staticmethod
    def embedding_config_validation(key: str, embedding_config_id: int):
        try:
            EmbeddingConfig.objects.get(pk=embedding_config_id)
        except EmbeddingConfig.DoesNotExist:
            message = f"'{key}' validation error.Reason: Embedding config with id {embedding_config_id} does not exists"
            raise ValidationError(message)

    @staticmethod
    def string_validation(key: str, value: str):
        if not isinstance(value, str):
            message = f"'{key}' validation error.Reason: {value} is not string"
            raise ValidationError(message)

    @staticmethod
    def boolean_validation(key: str, value: bool):
        if not isinstance(value, bool):
            message = f"'{key}' validation error.Reason: {value} is not boolean"
            raise ValidationError(message)

    @staticmethod
    def integer_validation(key: str, value: int):
        if not isinstance(value, int):
            message = f"'{key}' validation error.Reason: {value} is not integer"
            raise ValidationError(message)

    @staticmethod
    def float_validation(key: str, value: float):
        if not isinstance(value, float):
            message = f"'{key}' validation error.Reason: {value} is not float"
            raise ValidationError(message)

    @staticmethod
    def any_validation(key: str, value):
        # TODO: Implement validation for "any" of ToolConfigField.FieldType.ANY
        pass

    VALIDATION_FUNCTIONS = {
        "llm_config": llm_config_validation,
        "embedding_config": embedding_config_validation,
        "string": string_validation,
        "boolean": boolean_validation,
        "integer": integer_validation,
        "float": float_validation,
        "any": any_validation,
    }

    def __init__(
        self,
        validate_null_fields: bool = True,
        validate_missing_reqired_fields: bool = True,
    ):
        self._validate_null_fields: bool = validate_null_fields
        self._validate_missing_reqired_fields: bool = validate_missing_reqired_fields

    def validate(
        self,
        name: str,
        tool: Tool,
        configuration: dict,
    ) -> ToolConfig:

        if self._validate_missing_reqired_fields:
            self.__validate_missing_fields(
                name=name, tool=tool, configuration=configuration
            )
        # takes fields from updated_models and compare with inputed
        tool_config_fields = tool.get_tool_config_fields()

        for key, value in configuration.items():
            # Do not validate null fields
            if value is None and not self._validate_null_fields:
                continue

            # Do not validate excessive fields
            if key not in tool_config_fields.keys():
                continue

            field = tool_config_fields.get(key)

            validation_function = self.VALIDATION_FUNCTIONS.get(field.data_type.lower())
            if not validation_function:
                raise KeyError(
                    f"Validation function for '{field.data_type}' does not exist."
                )
            else:
                validation_function(key, value)
        # TODO: take object creation OUT of the function `validate`
        return ToolConfig(name=name, tool=tool, configuration=configuration)

    def validate_is_completed(self, tool_id: int, configuration: dict) -> bool:
        """
        Usage:
            Used in `to_representation` method in `ToolConfigSerializer`.
            Only for GET requests to endpoints: /tool-config/, /tool-config/{id}/.

        Goal:
            To verify whether all fields in the configuration for each specific TOOL remain valid.

        Args:
            tool_id (int): To get required predifined configuration for this tool.
            configuration (dict): tool configuration need to be validate.

        Raises:
            This validation function raises nothing, but only return bool value(is_completed) about passing validation.
            Returns `False` if:
                - `tool_id` is not an integer.
                - Any required field is missing from `configuration`.
                - Validation for any field fails.

        Notes:
            The function is designed to not raise validation exceptions directly but
            instead returns a boolean value to indicate the validation status.
        """
        is_completed: bool = True

        if not isinstance(tool_id, int):
            return False

        tool_required_fields = ToolConfigField.objects.filter(
            tool_id=tool_id, required=True
        )

        for field in tool_required_fields:
            if field.name not in configuration:
                return False

            value = configuration.get(field.name)
            validation_function = self.VALIDATION_FUNCTIONS.get(field.data_type.lower())

            if not validation_function:
                raise KeyError(
                    f"Validation function for '{field.data_type}' does not exist."
                )

            try:
                validation_function(field.name, value)
            except ValidationError:
                return False

        return is_completed

    def __validate_missing_fields(
        self,
        name: str,
        tool: Tool,
        configuration: dict,
    ):
        missing_fields = self.__get_missing_required_fields(
            tool=tool, configuration=configuration
        )
        if missing_fields:
            message = (
                f"Missing keys for tool config {name}: {', '.join(missing_fields)}"
            )
            raise ValidationError(message)

    def __get_missing_required_fields(
        self, tool: Tool, configuration: dict[str, Any]
    ) -> set[str]:
        required_field_names = ToolConfigField.objects.filter(
            tool=tool, required=True
        ).values_list("name", flat=True)
        return set(required_field_names) - set(configuration.keys())


def validate_session(schema: dict):

    crew_name = schema["crew"]["name"]
    tasks = schema["crew"]["tasks"]
    agents = schema["crew"]["agents"]

    if len(tasks) == 0:
        raise ValueError(f"No tasks provided for {crew_name}")
    if len(agents) == 0:
        raise ValueError(f"No agents provided {crew_name}")

    agent_roles = [agent["role"] for agent in agents]

    for task in tasks:
        if task["agent"]["role"] not in agent_roles:
            task_name = task["name"]
            agent_role = task["agent"]["role"]
            raise ValueError(
                f"Agent {agent_role} assigned for task {task_name} not found in crew {crew_name}"
            )


def validate_tool_configs(crew: Crew) -> list[ToolConfig]:

    configured_tool_ids: Iterable[int] = Agent.objects.filter(crew=crew).values_list(
        "configured_tools", flat=True
    )

    validator = ToolConfigValidator(
        validate_missing_reqired_fields=True, validate_null_fields=True
    )

    configured_tool_set = ToolConfig.objects.filter(pk__in=configured_tool_ids)

    evaled_tool_confgs = list()
    for tool_config in configured_tool_set:

        evaled_tool_confgs.append(
            validator.validate(
                name=tool_config.name,
                tool=tool_config.tool,
                configuration=tool_config.configuration,
            )
        )

    return evaled_tool_confgs
