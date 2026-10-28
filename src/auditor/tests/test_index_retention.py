"""Which tiered monthly index an audit event lands in, and how long ISM keeps that index."""

from datetime import datetime, timedelta, timezone

import pytest
from loguru import logger

from app.domains.base import IndexSpec
from app.domains.sessions.index import SESSIONS_INDEX
from app.index_setup.retention import ism_policy
from app.repositories.index_routing import index_name_for
from src.shared.models import SessionAuditEvent

RECEIVED_AT = datetime(2026, 10, 31, 23, 59, tzinfo=timezone.utc)


def _event(retention_days: int, event_time: datetime = RECEIVED_AT) -> SessionAuditEvent:
    return SessionAuditEvent(
        id="evt-1",
        org_id=7,
        session_id=1,
        kind="event",
        event_time=event_time,
        retention_days=retention_days,
    )


def _states(policy: dict) -> dict[str, dict]:
    return {state["name"]: state for state in policy["policy"]["states"]}


@pytest.fixture
def warnings():
    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="WARNING")
    yield messages
    logger.remove(sink_id)


def test_index_name_for_tier_and_month():
    assert index_name_for(SESSIONS_INDEX, _event(90), RECEIVED_AT) == "audit_events-90d-2026.10"


@pytest.mark.parametrize(
    "retention_days, expected",
    [
        (0, "audit_events-unlimited-2026.10"),
        (30, "audit_events-30d-2026.10"),
        (90, "audit_events-90d-2026.10"),
        (180, "audit_events-180d-2026.10"),
        (365, "audit_events-365d-2026.10"),
    ],
)
def test_each_retention_choice_has_its_own_tier(retention_days, expected):
    assert index_name_for(SESSIONS_INDEX, _event(retention_days), RECEIVED_AT) == expected


def test_month_is_taken_in_utc():
    # 01:30 on 1 November in UTC+2 is still 31 October in UTC.
    received_east_of_utc = datetime(2026, 11, 1, 1, 30, tzinfo=timezone(timedelta(hours=2)))

    assert index_name_for(SESSIONS_INDEX, _event(30), received_east_of_utc) == "audit_events-30d-2026.10"


def test_routing_ignores_a_skewed_event_time():
    skewed_event = _event(90, event_time=datetime(2026, 12, 25, tzinfo=timezone.utc))

    assert index_name_for(SESSIONS_INDEX, skewed_event, RECEIVED_AT) == "audit_events-90d-2026.10"


@pytest.mark.parametrize("retention_days", [45, -1])
def test_unknown_retention_goes_to_unlimited(retention_days, warnings):
    assert index_name_for(SESSIONS_INDEX, _event(retention_days), RECEIVED_AT) == "audit_events-unlimited-2026.10"
    assert any(str(retention_days) in message and "evt-1" in message for message in warnings)


def test_known_retention_logs_no_warning(warnings):
    index_name_for(SESSIONS_INDEX, _event(90), RECEIVED_AT)

    assert warnings == []


@pytest.mark.parametrize("days", [0, 30, 90, 180, 365])
def test_ism_read_only_after_33_days(days):
    states = _states(ism_policy(SESSIONS_INDEX, days))

    assert ism_policy(SESSIONS_INDEX, days)["policy"]["default_state"] == "open"
    assert states["open"]["actions"] == []
    assert states["open"]["transitions"] == [
        {"state_name": "read_only", "conditions": {"min_index_age": "33d"}}
    ]
    assert states["read_only"]["actions"] == [{"read_only": {}}]


@pytest.mark.parametrize(
    "days, delete_age", [(30, "63d"), (90, "123d"), (180, "213d"), (365, "398d")]
)
def test_ism_deletes_after_tier_plus_33_days(days, delete_age):
    states = _states(ism_policy(SESSIONS_INDEX, days))

    assert states["read_only"]["transitions"] == [
        {"state_name": "delete", "conditions": {"min_index_age": delete_age}}
    ]
    assert states["delete"]["actions"] == [{"delete": {}}]


def test_unlimited_has_no_delete_transition():
    states = _states(ism_policy(SESSIONS_INDEX, 0))

    assert states["read_only"]["transitions"] == []
    assert "delete" not in states


@pytest.mark.parametrize(
    "days, policy_id, pattern",
    [
        (0, "audit-retention-unlimited", "audit_events-unlimited-*"),
        (30, "audit-retention-30d", "audit_events-30d-*"),
        (90, "audit-retention-90d", "audit_events-90d-*"),
        (180, "audit-retention-180d", "audit_events-180d-*"),
        (365, "audit-retention-365d", "audit_events-365d-*"),
    ],
)
def test_policy_ids_and_patterns_for_every_tier(days, policy_id, pattern):
    policy = ism_policy(SESSIONS_INDEX, days)["policy"]

    assert policy["policy_id"] == policy_id
    assert [template["index_patterns"] for template in policy["ism_template"]] == [[pattern]]


def test_ism_policy_rejects_a_value_outside_the_choices():
    with pytest.raises(ValueError):
        ism_policy(SESSIONS_INDEX, 45)


def test_another_domain_gets_its_own_index_names_policy_ids_and_patterns():
    other_index = IndexSpec(
        name="chat_audit",
        mapping_path=SESSIONS_INDEX.mapping_path,
        sort_keys=(),
        ism_policy_prefix="chat-audit-retention",
    )
    policy = ism_policy(other_index, 90)["policy"]

    assert index_name_for(other_index, _event(90), RECEIVED_AT) == "chat_audit-90d-2026.10"
    assert policy["policy_id"] == "chat-audit-retention-90d"
    assert policy["ism_template"][0]["index_patterns"] == ["chat_audit-90d-*"]
