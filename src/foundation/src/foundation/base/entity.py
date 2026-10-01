from typing import Any

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Entity"]


class Entity(BaseModel):
    """A domain entity, identified by a stable ``id``."""

    id: Any = Field(default=None, frozen=True)

    model_config = ConfigDict(from_attributes=True, validate_assignment=True)
