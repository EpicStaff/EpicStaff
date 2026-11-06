from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers
from src.shared.models.system_one import SYSTEM_ONE_QUESTIONS_ADAPTER


def validate_system_one_questions(value) -> dict:
    """Validate a System One entry's questions and return them in ST2's normalised form.

    An empty dict is accepted: an entry may be saved before its questions are written.
    """
    if not isinstance(value, dict):
        raise serializers.ValidationError("Questions must be an object.")
    if not value:
        return {}
    try:
        validated = SYSTEM_ONE_QUESTIONS_ADAPTER.validate_python(value)
    except PydanticValidationError as exc:
        raise serializers.ValidationError(
            [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]
        ) from exc
    return SYSTEM_ONE_QUESTIONS_ADAPTER.dump_python(validated, mode="json", exclude_none=True)


def validate_input_map(value: dict) -> dict:
    if not isinstance(value, dict) or not all(
        isinstance(name, str) and isinstance(path, str) for name, path in value.items()
    ):
        raise serializers.ValidationError("Map each name to a variable path.")
    return value
