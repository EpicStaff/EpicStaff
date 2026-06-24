from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class Message(BaseModel):
    """Unit of data exchanged between services."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    payload: dict[str, Any]
