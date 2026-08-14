from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class SessionAuditEvent(BaseModel):
    # OpenSearch columns
    id: str
    parent_id: str = ""

    # Postgres columns
    session_id: int
    session_message_id: str | None = None

    kind: Literal["session", "node", "event"]
    status: Literal["completed", "failed"] | None = None

    name: str = ""
    flow_name: str = ""
    node_type: str = ""

    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    details: dict[str, Any] = {}

    event_time: datetime
    record_time: datetime | None = None

    org_id: int

    model_config = ConfigDict(from_attributes=True)
