from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError
from rest_framework import serializers
from src.shared.models import LLMConfigData

# The JSON columns accept any JSON, but every consumer loads the config into
# LLMConfigData. Validating against its own annotations keeps one rule for both.
_FIELD_ADAPTERS = {
    name: TypeAdapter(LLMConfigData.model_fields[name].annotation)
    for name in ("stop", "logit_bias", "extra_headers")
}

_FIELD_SHAPES = {
    "stop": "a string or a list of strings",
    "logit_bias": "an object mapping integer token ids to numbers",
    "extra_headers": "an object mapping header names to string values",
}


def _validate_shape(field_name: str, value):
    try:
        _FIELD_ADAPTERS[field_name].validate_python(value)
    except PydanticValidationError:
        raise serializers.ValidationError(
            f"{field_name} must be {_FIELD_SHAPES[field_name]}."
        ) from None
    # The stored value keeps its JSON form (e.g. string token-id keys).
    return value


class LLMConfigDataFieldsValidationMixin:
    """Reject stop, logit_bias and extra_headers values LLMConfigData cannot load."""

    def validate_stop(self, value):
        return _validate_shape("stop", value)

    def validate_logit_bias(self, value):
        return _validate_shape("logit_bias", value)

    def validate_extra_headers(self, value):
        return _validate_shape("extra_headers", value)
