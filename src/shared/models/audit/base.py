from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict


class BaseAuditEvent(BaseModel):
    """Fields every audit domain's event model must have - depended on
    structurally by the shared OpenSearchAuditRepository (id, record_time),
    the shared ScopingPolicy (org_id, event_time as the retention/sort
    field convention), and app/services/matching.py (filter_matched).

    Attributes:
        retention_days: Days auditor keeps the event; 0 (also the default) keeps it
            forever. Storage metadata: sent and stored, never shown to a reader.
    """

    # Fields that travel to auditor and into the index but are left out of every
    # search result and export, through public_dump and public_field_names.
    STORAGE_ONLY_FIELDS: ClassVar[frozenset[str]] = frozenset({"retention_days"})

    id: str
    org_id: int
    event_time: datetime
    record_time: datetime | None = None
    filter_matched: bool = False

    retention_days: int = 0

    model_config = ConfigDict(from_attributes=True)

    def public_dump(self) -> dict[str, Any]:
        """Return the event as JSON-ready data for a reader, without the storage-only fields."""
        return self.model_dump(mode="json", exclude=set(self.STORAGE_ONLY_FIELDS))

    @classmethod
    def public_field_names(cls) -> list[str]:
        """Return the field names public_dump emits, in declaration order."""
        return [name for name in cls.model_fields if name not in cls.STORAGE_ONLY_FIELDS]
