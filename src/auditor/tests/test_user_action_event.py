from datetime import datetime, timezone

from src.shared.models import UserAction, UserActionEvent


def test_user_action_event_round_trips_and_hides_retention():
    event = UserActionEvent(
        id="evt-1",
        number=17,
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
    assert event.public_dump()["number"] == 17
    assert UserActionEvent.model_validate(event.model_dump(mode="json")) == event


def test_export_columns_include_the_record_number():
    assert "number" in UserActionEvent.public_field_names()


def test_record_stored_before_numbering_still_reads():
    stored = {
        "id": "evt-old",
        "org_id": 7,
        "event_time": "2026-10-30T12:00:00Z",
        "actor_user_id": 42,
        "actor_email": "user@example.com",
        "action": "created",
    }

    assert UserActionEvent.model_validate(stored).public_dump()["number"] is None
