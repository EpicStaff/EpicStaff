from pathlib import Path

from app.domains.base import IndexSpec

USER_ACTIONS_INDEX = IndexSpec(
    name="audit_user_actions",
    mapping_path=Path(__file__).parent / "mappings" / "0001_audit_user_actions.json",
    sort_keys=(("event_time", "desc"), ("id", "desc")),
    ism_policy_prefix="audit-user-actions-retention",
)
