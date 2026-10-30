from datetime import datetime, timezone

from src.shared.models import UserAction, UserActionEvent


def test_user_action_event_round_trips_and_hides_retention():
    event = UserActionEvent(
        id="evt-1",
        org_id=7,
        event_time=datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc),
        actor_user_id=42,
        actor_email="user@example.com",
        action=UserAction.RENAMED,
        target_type="flow",
        target_id="5",
        target_name="New name",
        previous_name="Old name",
        retention_days=90,
    )

    assert "retention_days" not in event.public_dump()
    assert UserActionEvent.model_validate(event.model_dump(mode="json")) == event
