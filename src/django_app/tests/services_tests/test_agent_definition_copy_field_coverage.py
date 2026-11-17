"""Every concrete field of a row the agent copy writes is copied, or left out on purpose.

The agent and surface copies name their fields one by one, so a field added to the
model later is dropped from every copy until someone adds it. The set tests fail on
such a field: copy it (AgentDefinitionCopyService.copy, SurfaceService.clone_surface)
or list it as deliberately not copied, then update the sets here. The round-trip
tests then give every field listed as copied a non-default value on the source and
check the copy holds it, so listing a field without copying it fails too.

RealtimeAgentDefinition needs no such test: its copy takes every concrete field
through copied_field_values, so a new field is copied by default.
"""

import pytest
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from agents.models import AgentDefinition, Surface
from agents.services.agent_definition_copy_service import AgentDefinitionCopyService
from rbac.models import Organization
from tables.models import Label, LLMConfig
from tests.fixtures import *  # noqa: F401,F403

AGENT_FIELDS_COPIED_FROM_SOURCE = {
    "description",
    "instruction_list",
    "metadata",
    "llm_config",
    "fallback_llm_config",
    "fcm_llm_config",
    "max_iter",
    "max_rpm",
    "max_execution_time",
    "cache",
    "max_retry_limit",
    "default_temperature",
    "max_tool_calls",
    "tool_timeout",
    "max_consecutive_failures",
    "schema_max_retries",
    "group",
}
# Set for the copy itself (a numbered name, the agent's org, the caller as author) or
# left to the row's own defaults (identity, timestamps, a live soft-delete state).
AGENT_FIELDS_NOT_COPIED = {
    "id",
    "name",
    "org",
    "created_by",
    "created_at",
    "active",
    "soft_deleted_at",
    "soft_delete_batch",
}

SURFACE_FIELDS_COPIED_FROM_SOURCE = {"org", "instructions"}
# The clone gets its own numbered name, the new agent as owner, no group (only a
# shared surface may have one) and the caller as author.
SURFACE_FIELDS_NOT_COPIED = {
    "id",
    "name",
    "owner_agent",
    "group",
    "created_by",
    "created_at",
    "updated_at",
    "active",
    "soft_deleted_at",
    "soft_delete_batch",
}


def _concrete_field_names(model) -> set[str]:
    return {field.name for field in model._meta.concrete_fields}


def test_every_agent_field_is_copied_or_deliberately_left_out():
    assert _concrete_field_names(AgentDefinition) == (
        AGENT_FIELDS_COPIED_FROM_SOURCE | AGENT_FIELDS_NOT_COPIED
    )


def test_every_surface_field_is_cloned_or_deliberately_left_out():
    assert _concrete_field_names(Surface) == (
        SURFACE_FIELDS_COPIED_FROM_SOURCE | SURFACE_FIELDS_NOT_COPIED
    )


def _validator_bound(field, validator_class):
    for validator in field.validators:
        if isinstance(validator, validator_class):
            return validator.limit_value
    return None


def _non_default_value(field, make_related):
    """A valid value for `field` that differs from its default.

    Raises on a field type it has no rule for, so a new kind of copied field gets
    an explicit rule here rather than going unchecked.
    """
    default = field.get_default()
    if isinstance(field, models.ForeignKey):
        return make_related(field)
    if isinstance(field, models.BooleanField):
        return not default
    if isinstance(field, (models.IntegerField, models.FloatField)):
        # The model validators bound these (max_iter 1..90 and so on); either end
        # is valid, and at most one of them is the default.
        low = _validator_bound(field, MinValueValidator)
        high = _validator_bound(field, MaxValueValidator)
        if high is None:
            return (default or 0) + 1
        return high if default != high else low
    if isinstance(field, (models.CharField, models.TextField)):
        return f"copied {field.name}"
    if isinstance(field, models.JSONField):
        # instruction_list holds {"name", "content"} items; the dict field is free-form.
        if isinstance(default, list):
            return [{"name": f"{field.name}.md", "content": "copied"}]
        return {"copied": field.name}
    raise AssertionError(f"No value rule for {field.name} ({type(field).__name__}).")


def _related_row_factory(org, llm_model):
    """Build a fresh related row per FK, so two FKs swapped in the copy don't compare equal."""

    def make_related(field):
        related_model = field.related_model
        if related_model is LLMConfig:
            return LLMConfig.objects.create(
                custom_name=f"copied {field.name}", model=llm_model, org=org
            )
        if related_model is Label:
            return Label.objects.create(
                name=f"copied {field.name}", org=org, scope=Label.Scope.AGENT
            )
        if related_model is Organization:
            # A copy stays in its source's org, so the only valid value is that org.
            return org
        raise AssertionError(f"No related row rule for {field.name} -> {related_model}.")

    return make_related


def _assert_copied(source, copy, field_names: set[str]) -> None:
    attnames = sorted(source._meta.get_field(name).attname for name in field_names)
    assert {attname: getattr(copy, attname) for attname in attnames} == {
        attname: getattr(source, attname) for attname in attnames
    }


@pytest.mark.django_db
def test_every_agent_field_listed_as_copied_reaches_the_copy(
    default_org, gpt_4o_llm, regular_user
):
    make_related = _related_row_factory(default_org, gpt_4o_llm)
    values = {
        name: _non_default_value(AgentDefinition._meta.get_field(name), make_related)
        for name in AGENT_FIELDS_COPIED_FROM_SOURCE
    }
    source = AgentDefinition.objects.create(org=default_org, name="Source", **values)
    source.refresh_from_db()

    copy = AgentDefinitionCopyService().copy(source, user=regular_user)

    copy.refresh_from_db()
    _assert_copied(source, copy, AGENT_FIELDS_COPIED_FROM_SOURCE)


@pytest.mark.django_db
def test_every_surface_field_listed_as_copied_reaches_the_clone(
    default_org, gpt_4o_llm, regular_user
):
    make_related = _related_row_factory(default_org, gpt_4o_llm)
    agent = AgentDefinition.objects.create(org=default_org, name="Owner")
    values = {
        name: _non_default_value(Surface._meta.get_field(name), make_related)
        for name in SURFACE_FIELDS_COPIED_FROM_SOURCE
    }
    source = Surface.objects.create(name="Owned", owner_agent=agent, **values)

    new_agent = AgentDefinitionCopyService().copy(agent, user=regular_user)

    clone = Surface.objects.get(owner_agent=new_agent)
    _assert_copied(source, clone, SURFACE_FIELDS_COPIED_FROM_SOURCE)
