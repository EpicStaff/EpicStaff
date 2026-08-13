from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class SessionAuditEvent(BaseModel):
    id: str
    org_id: int
    session_message_id: str | None = None
    parent_id: str = ""
    session_id: int

    kind: Literal["session", "node", "event"]
    name: str = ""
    flow_name: str = ""
    node_type: str = ""
    status: Literal["completed", "failed"]

    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    details: dict[str, Any] = {}

    event_time: datetime
    record_time: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
