from pathlib import Path

from app.domains.base import IndexSpec

SESSIONS_INDEX = IndexSpec(
    name="audit_events",
    mapping_path=Path(__file__).parent / "mappings" / "0001_audit_events.json",
    sort_keys=(("event_time", "desc"), ("id", "desc")),
)
