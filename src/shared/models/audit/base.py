from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BaseAuditEvent(BaseModel):
    """Fields every audit domain's event model must have - depended on
    structurally by the shared OpenSearchAuditRepository (id, record_time),
    the shared ScopingPolicy (org_id, event_time as the retention/sort
    field convention), and app/services/matching.py (filter_matched)."""

    id: str
    org_id: int
    event_time: datetime
    record_time: datetime | None = None
    filter_matched: bool = False

    model_config = ConfigDict(from_attributes=True)
