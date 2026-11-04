import re

import pytest

from src.shared.envtools import Env
from src.shared.retention import (
    RETENTION_CHOICES,
    DataType,
    RetentionPolicy,
    RetentionRule,
    allowed_org_values,
    audit_tier,
    effective_retention_days,
    load_retention_policy,
)

VALID_ENVIRONMENT = {
    "RETENTION_SESSIONS_DAYS": "30",
    "RETENTION_SESSION_MAX_DAYS": "90",
    "RETENTION_CONVERSATIONS_DAYS": "0",
    "RETENTION_CONVERSATION_MAX_DAYS": "none",
    "RETENTION_AUDIT_DAYS": "365",
    "RETENTION_AUDIT_MAX_DAYS": "365",
}

MISSING = object()


@pytest.fixture
def env_factory():
    """Build an Env over VALID_ENVIRONMENT with overrides; MISSING drops a variable."""

    def build(**overrides) -> Env:
        environment = {**VALID_ENVIRONMENT, **overrides}
        return Env({name: value for name, value in environment.items() if value is not MISSING})

    yield build


def test_load_builds_one_rule_per_data_type(env_factory):
    policy = load_retention_policy(env_factory())

    assert policy == RetentionPolicy(
        rules={
            DataType.SESSIONS: RetentionRule(default_days=30, max_days=90),
            DataType.CONVERSATIONS: RetentionRule(default_days=0, max_days=None),
            DataType.AUDIT: RetentionRule(default_days=365, max_days=365),
        }
    )


@pytest.mark.parametrize(
    "variable",
    ["RETENTION_SESSIONS_DAYS", "RETENTION_CONVERSATIONS_DAYS", "RETENTION_AUDIT_DAYS"],
)
def test_load_requires_all_three_defaults(env_factory, variable):
    with pytest.raises(ValueError, match=f"^{variable}"):
        load_retention_policy(env_factory(**{variable: MISSING}))


@pytest.mark.parametrize(
    "cap_value",
    [MISSING, "none", "None"],
    ids=["absent", "none", "None"],
)
def test_load_treats_absent_or_none_cap_as_uncapped(env_factory, cap_value):
    policy = load_retention_policy(env_factory(RETENTION_SESSION_MAX_DAYS=cap_value))

    assert policy.rules[DataType.SESSIONS].max_days is None


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("RETENTION_SESSIONS_DAYS", "45"),
        ("RETENTION_CONVERSATIONS_DAYS", "-30"),
        ("RETENTION_AUDIT_DAYS", "366"),
        ("RETENTION_AUDIT_DAYS", "none"),
        ("RETENTION_SESSION_MAX_DAYS", "60"),
        ("RETENTION_AUDIT_MAX_DAYS", "400"),
    ],
)
def test_load_rejects_value_outside_list(env_factory, variable, value):
    with pytest.raises(ValueError, match=f"^{variable}"):
        load_retention_policy(env_factory(**{variable: value}))


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("RETENTION_SESSIONS_DAYS", "thirty"),
        ("RETENTION_AUDIT_DAYS", "30d"),
        ("RETENTION_CONVERSATIONS_DAYS", ""),
        ("RETENTION_SESSION_MAX_DAYS", "90.0"),
    ],
)
def test_load_rejects_non_integer_value(env_factory, variable, value):
    with pytest.raises(ValueError, match=re.escape(f"{variable}={value!r} must be a whole number")):
        load_retention_policy(env_factory(**{variable: value}))


def test_load_rejects_default_above_cap(env_factory):
    environment = env_factory(RETENTION_SESSIONS_DAYS="365", RETENTION_SESSION_MAX_DAYS="90")

    with pytest.raises(ValueError, match="^RETENTION_SESSIONS_DAYS"):
        load_retention_policy(environment)


def test_load_accepts_default_equal_to_cap(env_factory):
    environment = env_factory(RETENTION_SESSIONS_DAYS="90", RETENTION_SESSION_MAX_DAYS="90")

    assert load_retention_policy(environment).rules[DataType.SESSIONS] == RetentionRule(90, 90)


def test_load_rejects_unlimited_default_with_cap(env_factory):
    environment = env_factory(RETENTION_AUDIT_DAYS="0", RETENTION_AUDIT_MAX_DAYS="365")

    with pytest.raises(ValueError, match="^RETENTION_AUDIT_DAYS"):
        load_retention_policy(environment)


def test_load_rejects_zero_cap(env_factory):
    environment = env_factory(RETENTION_SESSIONS_DAYS="30", RETENTION_SESSION_MAX_DAYS="0")

    with pytest.raises(ValueError, match="^RETENTION_SESSION_MAX_DAYS"):
        load_retention_policy(environment)


def test_load_without_audit_floor_sets_no_floor_anywhere(env_factory):
    policy = load_retention_policy(env_factory())

    assert [rule.min_days for rule in policy.rules.values()] == [None, None, None]


@pytest.mark.parametrize("floor_value", [MISSING, "none", "None"], ids=["absent", "none", "None"])
def test_load_treats_absent_or_none_audit_floor_as_no_floor(env_factory, floor_value):
    policy = load_retention_policy(env_factory(RETENTION_AUDIT_MIN_DAYS=floor_value))

    assert policy.rules[DataType.AUDIT].min_days is None


def test_load_reads_the_audit_floor(env_factory):
    policy = load_retention_policy(env_factory(RETENTION_AUDIT_MIN_DAYS="90"))

    assert policy.rules[DataType.AUDIT] == RetentionRule(365, 365, min_days=90)
    assert policy.rules[DataType.SESSIONS].min_days is None
    assert policy.rules[DataType.CONVERSATIONS].min_days is None


@pytest.mark.parametrize("value", ["0", "45", "400", "-90"])
def test_load_rejects_audit_floor_outside_list(env_factory, value):
    with pytest.raises(ValueError, match=r"^RETENTION_AUDIT_MIN_DAYS=-?\d+ must be one of"):
        load_retention_policy(env_factory(RETENTION_AUDIT_MIN_DAYS=value))


def test_load_rejects_non_integer_audit_floor(env_factory):
    with pytest.raises(
        ValueError, match=re.escape("RETENTION_AUDIT_MIN_DAYS='ninety' must be a whole number")
    ):
        load_retention_policy(env_factory(RETENTION_AUDIT_MIN_DAYS="ninety"))


def test_load_rejects_audit_floor_above_cap(env_factory):
    environment = env_factory(
        RETENTION_AUDIT_DAYS="180", RETENTION_AUDIT_MAX_DAYS="180", RETENTION_AUDIT_MIN_DAYS="365"
    )

    with pytest.raises(ValueError, match="^RETENTION_AUDIT_MIN_DAYS=365 is above the cap"):
        load_retention_policy(environment)


def test_load_rejects_audit_default_below_floor(env_factory):
    environment = env_factory(
        RETENTION_AUDIT_DAYS="30", RETENTION_AUDIT_MAX_DAYS="none", RETENTION_AUDIT_MIN_DAYS="90"
    )

    with pytest.raises(ValueError, match="^RETENTION_AUDIT_DAYS=30 is below its floor"):
        load_retention_policy(environment)


@pytest.mark.parametrize(
    ("default_days", "max_days", "min_days"),
    [("0", "none", "90"), ("90", "none", "90"), ("90", "90", "90"), ("180", "365", "90")],
    ids=["forever-default-above-any-floor", "default-at-floor", "floor-equals-cap", "between"],
)
def test_load_accepts_consistent_audit_floor(env_factory, default_days, max_days, min_days):
    environment = env_factory(
        RETENTION_AUDIT_DAYS=default_days,
        RETENTION_AUDIT_MAX_DAYS=max_days,
        RETENTION_AUDIT_MIN_DAYS=min_days,
    )

    assert load_retention_policy(environment).rules[DataType.AUDIT].min_days == int(min_days)


def test_effective_inherits_default_when_org_value_empty():
    assert effective_retention_days(None, RetentionRule(30, None)) == 30


@pytest.mark.parametrize(
    ("org_days", "rule", "expected"),
    [
        (0, RetentionRule(30, None), 0),
        (365, RetentionRule(30, None), 365),
        (30, RetentionRule(30, 90), 30),
        (90, RetentionRule(30, 90), 90),
        (365, RetentionRule(30, 90), 90),
        (0, RetentionRule(30, 90), 90),
        (None, RetentionRule(0, None), 0),
        (None, RetentionRule(90, 90), 90),
        (30, RetentionRule(365, None, min_days=90), 90),
        (90, RetentionRule(365, None, min_days=90), 90),
        (180, RetentionRule(365, None, min_days=90), 180),
        (0, RetentionRule(365, None, min_days=90), 0),
        (30, RetentionRule(90, 180, min_days=90), 90),
        (365, RetentionRule(90, 180, min_days=90), 180),
        (0, RetentionRule(90, 180, min_days=90), 180),
    ],
    ids=[
        "forever-uncapped",
        "above-default-uncapped",
        "under-cap",
        "equal-to-cap",
        "above-cap-clamped",
        "forever-clamped-to-cap",
        "inherits-forever-default",
        "inherits-capped-default",
        "below-floor-raised",
        "equal-to-floor",
        "above-floor",
        "forever-above-floor",
        "below-floor-raised-under-cap",
        "above-cap-clamped-with-floor",
        "forever-clamped-to-cap-with-floor",
    ],
)
def test_effective_retention_days(org_days, rule, expected):
    assert effective_retention_days(org_days, rule) == expected


def test_allowed_org_values_respects_cap():
    assert allowed_org_values(RetentionRule(30, 90)) == (30, 90)
    assert allowed_org_values(RetentionRule(30, None)) == (0, 30, 90, 180, 365)
    assert allowed_org_values(RetentionRule(0, None)) == (0, 30, 90, 180, 365)
    assert allowed_org_values(RetentionRule(365, 365)) == (30, 90, 180, 365)


def test_allowed_org_values_respects_floor():
    assert allowed_org_values(RetentionRule(365, None, min_days=90)) == (0, 90, 180, 365)
    assert allowed_org_values(RetentionRule(90, 180, min_days=90)) == (90, 180)
    assert allowed_org_values(RetentionRule(365, 365, min_days=365)) == (365,)


def test_audit_tier_names():
    assert [audit_tier(days) for days in RETENTION_CHOICES] == ["unlimited", "30d", "90d", "180d", "365d"]


@pytest.mark.parametrize("days", [-1, 1, 45, 366])
def test_audit_tier_rejects_days_outside_choices(days):
    with pytest.raises(ValueError, match=rf"^Invalid retention days: {days}\."):
        audit_tier(days)
