"""One class per setting value type: its JSON Schema fragment, UI hints and annotation match."""

from abc import ABC, abstractmethod
from types import NoneType, UnionType
from typing import ClassVar, Literal, Union, get_args, get_origin

from ai_models.domain.specs import ModelSpec, ParameterSpec

_PERCENT_CONTROL = "percent"
# A UI hint for the slider and stepper increment; not `multipleOf`, so a stored value
# off the step stays valid.
_STEP_HINT = "x-step"


def _single_type(annotation: object) -> object | None:
    """Return `X` for `X` or `X | None`; None for a union of several types."""
    if get_origin(annotation) in (Union, UnionType):
        members = [member for member in get_args(annotation) if member is not NoneType]
        return members[0] if len(members) == 1 else None
    return annotation


class BaseValueType(ABC):
    """A setting value type. A `None` default means "not set", so the schema also allows null."""

    name: ClassVar[str]
    _json_type: ClassVar[str]

    def schema_fragment(self, spec: ParameterSpec, model: ModelSpec | None) -> dict:
        """Return the JSON Schema of `spec`'s value, with UI hints, for `model` (None: unknown)."""
        # The form resets a setting to this default, so it must be a value the model takes.
        default = self._fitted_default(spec, model)
        fragment = {
            "type": self._json_type if default is not None else [self._json_type, "null"],
            "title": spec.label,
            "description": spec.help_text,
            "default": default,
            "x-widget": spec.control,
            "x-group": spec.group,
        }
        fragment.update(self._constraints(spec, model, default))
        return fragment

    def _fitted_default(self, spec: ParameterSpec, model: ModelSpec | None) -> object:
        """Return the registry default as `model` accepts it; None when it has no such value."""
        return spec.default

    def _constraints(self, spec: ParameterSpec, model: ModelSpec | None, default: object) -> dict:
        return {}

    @classmethod
    @abstractmethod
    def matches_annotation(cls, annotation: object) -> bool:
        """Whether a LiteLLM type hint describes a value of this type."""


class NumberValueType(BaseValueType):
    name = "number"
    _json_type = "number"
    _python_type: ClassVar[type] = float

    def _fitted_default(self, spec: ParameterSpec, model: ModelSpec | None) -> object:
        maximum = self._maximum(spec, model)
        if spec.default is None or maximum is None:
            return spec.default
        return min(spec.default, maximum)

    def _maximum(self, spec: ParameterSpec, model: ModelSpec | None) -> float | None:
        if spec.limit_from and model is not None and spec.limit_from in model.limits:
            return model.limits[spec.limit_from]
        return spec.maximum

    def _constraints(self, spec: ParameterSpec, model: ModelSpec | None, default: object) -> dict:
        constraints = {}
        if spec.minimum is not None:
            constraints["minimum"] = spec.minimum
        maximum = self._maximum(spec, model)
        if maximum is not None:
            constraints["maximum"] = maximum
        if spec.step is not None:
            constraints[_STEP_HINT] = spec.step
        if spec.control == _PERCENT_CONTROL:
            constraints["x-scale"] = 100
        return constraints

    @classmethod
    def matches_annotation(cls, annotation: object) -> bool:
        return _single_type(annotation) is cls._python_type


class IntegerValueType(NumberValueType):
    name = "integer"
    _json_type = "integer"
    _python_type = int


class BooleanValueType(BaseValueType):
    name = "boolean"
    _json_type = "boolean"

    @classmethod
    def matches_annotation(cls, annotation: object) -> bool:
        return _single_type(annotation) is bool


class ChoiceValueType(BaseValueType):
    name = "choice"
    _json_type = "string"

    def _fitted_default(self, spec: ParameterSpec, model: ModelSpec | None) -> object:
        # A default the model does not offer is "not set", like a null default.
        return spec.default if spec.default in self._options(spec, model) else None

    def _options(self, spec: ParameterSpec, model: ModelSpec | None) -> tuple:
        if model is not None and spec.name in model.options:
            return model.options[spec.name]
        return spec.options

    def _constraints(self, spec: ParameterSpec, model: ModelSpec | None, default: object) -> dict:
        # JSON Schema's enum also restricts null, so a "not set" default must be listed.
        return {"enum": [*self._options(spec, model), *([None] if default is None else [])]}

    @classmethod
    def matches_annotation(cls, annotation: object) -> bool:
        return get_origin(_single_type(annotation)) is Literal


class TextValueType(BaseValueType):
    name = "text"
    _json_type = "string"

    @classmethod
    def matches_annotation(cls, annotation: object) -> bool:
        return _single_type(annotation) is str


class TextListValueType(BaseValueType):
    name = "text_list"
    _json_type = "array"

    def _constraints(self, spec: ParameterSpec, model: ModelSpec | None, default: object) -> dict:
        return {"items": {"type": "string"}}

    @classmethod
    def matches_annotation(cls, annotation: object) -> bool:
        single = _single_type(annotation)
        return get_origin(single) is list and get_args(single) == (str,)


class JsonValueType(BaseValueType):
    name = "json"
    _json_type = "object"

    @classmethod
    def matches_annotation(cls, annotation: object) -> bool:
        single = _single_type(annotation)
        return single is dict or get_origin(single) is dict


class ValueTypeRegistry:
    """Look up value types by name, or guess one from a LiteLLM type hint."""

    def __init__(self) -> None:
        value_types = (
            BooleanValueType(),
            IntegerValueType(),
            NumberValueType(),
            ChoiceValueType(),
            TextValueType(),
            TextListValueType(),
            JsonValueType(),
        )
        self._value_types = {value_type.name: value_type for value_type in value_types}

    def get(self, name: str) -> BaseValueType:
        try:
            return self._value_types[name]
        except KeyError:
            raise ValueError(f"Unknown value type: {name!r}") from None

    def guess(self, annotation: object) -> BaseValueType:
        """Return the type matching `annotation`; JSON when none does."""
        return next(
            (
                value_type
                for value_type in self._value_types.values()
                if value_type.matches_annotation(annotation)
            ),
            self._value_types[JsonValueType.name],
        )
