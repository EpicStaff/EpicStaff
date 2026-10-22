from pydantic import BaseModel, ConfigDict

__all__ = ["ValueObject"]


class ValueObject(BaseModel):
    """An immutable value, identified by all its attributes."""

    model_config = ConfigDict(frozen=True, from_attributes=True)
