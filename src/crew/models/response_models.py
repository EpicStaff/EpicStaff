from enum import Enum
from typing import Any
from pydantic import BaseModel


class RunCrewModel(BaseModel):
    crew_id: int


class SessionStatus(Enum):
    PENDING = "pending"
    END = "end"
    RUN = "run"
    WAIT_FOR_USER = "wait_for_user"
    ERROR = "error"
    STOP = "stop"
    EXPIRED = "expired"


class ToolResponse(BaseModel):
    data: Any
