from typing import Any, Literal

from pydantic import Field

from .base import BaseAuditEvent


class SessionAuditEvent(BaseAuditEvent):
    # OpenSearch columns
    parent_id: str = ""

    # Postgres columns
    session_id: int
    session_message_id: str | None = None

    kind: Literal["session", "node", "event"]
    status: Literal["completed", "failed"] | None = None

    name: str = ""
    flow_name: str = ""
    node_type: str = ""

    run_type: str = ""

    input: dict[str, Any] | None = None
    output: dict[str, Any] | None = None
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
