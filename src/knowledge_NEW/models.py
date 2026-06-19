from typing import Any

from pydantic import (
    BaseModel,
    Field,
    ConfigDict,
)

__all__ = [
    "ValueObject",
    "Entity",
]


class ValueObject(BaseModel):
    """Base for immutable value objects — frozen after creation and compared by value."""

    model_config = ConfigDict(frozen=True)


class Entity(BaseModel):
    """Base for domain entities identified by a stable `id`."""

    id: Any = Field(frozen=True)

    model_config = ConfigDict(validate_assignment=True)
