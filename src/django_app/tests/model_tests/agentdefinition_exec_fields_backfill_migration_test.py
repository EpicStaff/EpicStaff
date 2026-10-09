from importlib import import_module

import pytest
from django.db import connection

from agents.models import AgentDefinition
from rbac.models import Organization

backfill_migration = import_module("agents.migrations.0010_agentdefinition_backfill_exec_fields")

NULLABLE_BEFORE_MIGRATION = (*backfill_migration.INTEGER_FIELD_RULES, "cache")


@pytest.fixture
def allow_null_execution_fields(db):
    """Recreate the pre-0011 schema so rows can hold NULL execution fields.

    Postgres DDL is transactional: the test transaction's rollback restores NOT NULL.
    """
    with connection.cursor() as cursor:
        for field_name in NULLABLE_BEFORE_MIGRATION:
            cursor.execute(
                f"ALTER TABLE agents_agentdefinition ALTER COLUMN {field_name} DROP NOT NULL;"
            )
    yield


@pytest.fixture
def organization(db):
    return Organization.objects.create(name="Backfill Org")


def _null_agent(organization, name):
    agent = AgentDefinition.objects.create(organization=organization, name=name)
    AgentDefinition.objects.filter(pk=agent.pk).update(
        **{field_name: None for field_name in NULLABLE_BEFORE_MIGRATION}
    )
    return agent


@pytest.mark.django_db
def test_nulls_take_singleton_values(allow_null_execution_fields, organization):
    agent = _null_agent(organization, "null-agent")
    singleton_values = {
        "max_iter": 25,
        "max_rpm": 10,
        "max_execution_time": 60,
        "max_retry_limit": 3,
        "schema_max_retries": 2,
        "max_tool_calls": 15,
        "tool_timeout": 300,
        "max_consecutive_failures": 3,
        "cache": True,
    }

    backfill_migration.backfill_execution_fields(AgentDefinition, singleton_values)

    agent.refresh_from_db()
    for field_name, value in singleton_values.items():
        assert getattr(agent, field_name) == value


@pytest.mark.django_db
def test_null_singleton_values_fall_back_to_new_defaults(
    allow_null_execution_fields, organization
):
    agent = _null_agent(organization, "null-agent")

    backfill_migration.backfill_execution_fields(AgentDefinition, {"max_rpm": None})

    agent.refresh_from_db()
    assert agent.max_iter == 15
    assert agent.max_rpm == 30
    assert agent.max_execution_time == 600
    assert agent.max_retry_limit == 3
    assert agent.schema_max_retries == 2
    assert agent.max_tool_calls == 15
    assert agent.tool_timeout == 300
    assert agent.max_consecutive_failures == 3
    assert agent.cache is False


@pytest.mark.django_db
def test_out_of_range_singleton_value_is_clamped_after_backfill(
    allow_null_execution_fields, organization
):
    agent = _null_agent(organization, "null-agent")

    backfill_migration.backfill_execution_fields(
        AgentDefinition, {"max_execution_time": 30, "tool_timeout": 5000}
    )

    agent.refresh_from_db()
    assert agent.max_execution_time == 60
    assert agent.tool_timeout == 1800


@pytest.mark.django_db
def test_out_of_range_values_are_clamped_and_in_range_values_kept(organization):
    too_low = AgentDefinition.objects.create(organization=organization, name="too-low")
    too_high = AgentDefinition.objects.create(organization=organization, name="too-high")
    in_range = AgentDefinition.objects.create(
        organization=organization, name="in-range", max_iter=42, default_temperature=None
    )
    AgentDefinition.objects.filter(pk=too_low.pk).update(
        max_iter=0,
        max_rpm=0,
        max_execution_time=1,
        max_retry_limit=-1,
        schema_max_retries=-1,
        max_tool_calls=0,
        tool_timeout=1,
        max_consecutive_failures=0,
        default_temperature=-1.0,
    )
    AgentDefinition.objects.filter(pk=too_high.pk).update(
        max_iter=1000,
        max_rpm=1000,
        max_execution_time=100_000,
        max_retry_limit=100,
        schema_max_retries=100,
        max_tool_calls=1000,
        tool_timeout=100_000,
        max_consecutive_failures=100,
        default_temperature=5.0,
    )

    backfill_migration.backfill_execution_fields(AgentDefinition, {})

    too_low.refresh_from_db()
    too_high.refresh_from_db()
    in_range.refresh_from_db()
    for field_name, (minimum, maximum, _default) in backfill_migration.INTEGER_FIELD_RULES.items():
        assert getattr(too_low, field_name) == minimum, field_name
        assert getattr(too_high, field_name) == maximum, field_name
    assert too_low.default_temperature == 0.0
    assert too_high.default_temperature == 2.0
    assert in_range.max_iter == 42
    assert in_range.default_temperature is None


@pytest.mark.django_db
@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_default_temperature_becomes_null(organization, value):
    agent = AgentDefinition.objects.create(organization=organization, name="non-finite")
    AgentDefinition.objects.filter(pk=agent.pk).update(default_temperature=value)

    backfill_migration.backfill_execution_fields(AgentDefinition, {})

    agent.refresh_from_db()
    assert agent.default_temperature is None
