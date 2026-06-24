from abc import abstractmethod, ABC
from enum import StrEnum
from typing import Any, Literal, Annotated, Union, Optional

from pydantic import BaseModel, Field, TypeAdapter, ConfigDict


__all__ = [
    "VariableTypeInput",
    "VariableType",
    "StringVariable",
    "NumberVariable",
    "BooleanVariable",
    "ObjectVariable",
    "ArrayVariable",
    "Variable",
    "variable_adapter",
    "StringNestedVariable",
    "NumberNestedVariable",
    "BooleanNestedVariable",
    "ObjectNestedVariable",
    "ArrayNestedVariable",
    "NestedVariable",
]

from ..dotdict import DotDict, DotList


class VariableTypeInput(StrEnum):
    AGENT = "agent_input"
    USER = "user_input"
    MIXED = "mixed"


class VariableType(StrEnum):
    ANY = "any"
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    OBJECT = "object"
    ARRAY = "array"


class BaseNestedVariable(BaseModel, ABC):
    type: VariableType
    description: Optional[str] = None
    default_value: Any = None

    model_config = ConfigDict(frozen=True)

    @property
    @abstractmethod
    def python_type(self):
        """Variable in Python type"""


class AnyNestedVariable(BaseNestedVariable):
    type: Literal[VariableType.ANY] = VariableType.ANY

    @property
    def python_type(self):
        return Any


class StringNestedVariable(BaseNestedVariable):
    type: Literal[VariableType.STRING] = VariableType.STRING
    default_value: str | None = None

    @property
    def python_type(self):
        return str


class NumberNestedVariable(BaseNestedVariable):
    type: Literal[VariableType.NUMBER] = VariableType.NUMBER
    default_value: int | float | None = None

    @property
    def python_type(self):
        return int | float


class BooleanNestedVariable(BaseNestedVariable):
    type: Literal[VariableType.BOOLEAN] = VariableType.BOOLEAN
    default_value: bool | None = None

    @property
    def python_type(self):
        return bool


class ObjectNestedVariable(BaseNestedVariable):
    type: Literal[VariableType.OBJECT] = VariableType.OBJECT
    default_value: DotDict | None = None
    properties: dict[str, "NestedVariable"]
    required_properties: list[str]

    @property
    def python_type(self):
        return DotDict


class ArrayNestedVariable(BaseNestedVariable):
    type: Literal[VariableType.ARRAY] = VariableType.ARRAY
    default_value: DotList | None = None
    item: "NestedVariable"

    @property
    def python_type(self):
        return DotList


NestedVariable = Annotated[
    Union[
        AnyNestedVariable,
        StringNestedVariable,
        NumberNestedVariable,
        BooleanNestedVariable,
        ObjectNestedVariable,
        ArrayNestedVariable,
    ],
    Field(discriminator="type"),
]


class BaseVariable(BaseModel):
    input_type: VariableTypeInput
    name: str
    required: bool = False

    model_config = ConfigDict(frozen=True)


class AnyVariable(BaseVariable, AnyNestedVariable):
    pass


class StringVariable(BaseVariable, StringNestedVariable):
    pass


class NumberVariable(BaseVariable, NumberNestedVariable):
    pass


class BooleanVariable(BaseVariable, BooleanNestedVariable):
    pass


class ObjectVariable(BaseVariable, ObjectNestedVariable):
    pass


class ArrayVariable(BaseVariable, ArrayNestedVariable):
    pass


Variable = Annotated[
    Union[
        AnyVariable,
        StringVariable,
        NumberVariable,
        BooleanVariable,
        ObjectVariable,
        ArrayVariable,
    ],
    Field(discriminator="type"),
]
variable_adapter = TypeAdapter(Variable)
