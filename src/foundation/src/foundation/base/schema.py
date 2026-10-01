from pydantic.config import ConfigDict
from pydantic.main import BaseModel

__all__ = ["Schema"]


class Schema(BaseModel):
    """An immutable schema for request and response payloads."""

    model_config = ConfigDict(frozen=True, from_attributes=True)
