"""org_visible_q / org_visible_queryset / OrgVisiblePrimaryKeyRelatedField must scope
every org-owned model by its owning-org FK, found by convention (named `org` on every
org-owned model, `tables` and `agents` alike), and must refuse a model without one
instead of returning it unfiltered."""

from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ImproperlyConfigured
from rest_framework import serializers

from agents.models import AgentDefinition, Surface
from rbac.models import Organization
from rbac.scoping.fields import (
    OrgScopedPrimaryKeyRelatedField,
    OrgVisiblePrimaryKeyRelatedField,
    org_visible_q,
    org_visible_queryset,
)
from tables.models import Label, LLMModel, Provider, PythonCode, PythonCodeTool
from tests.rbac_cross_org_fixtures import *  # noqa: F401,F403


OWNING_ORG_FK_NAME = "org"


def test_every_fk_to_organization_follows_naming_convention():
    misnamed = [
        f"{model._meta.label}.{field.name}"
        for model in apps.get_models()
        for field in model._meta.get_fields()
        if field.concrete
        and (field.many_to_one or field.one_to_one)
        and field.related_model is Organization
        and field.name != OWNING_ORG_FK_NAME
    ]

    assert not misnamed, (
        f"ForeignKey/OneToOneField to Organization not named '{OWNING_ORG_FK_NAME}': "
        f"{misnamed}. org_visible_q finds the owning org by that name only — rename "
        f"the field to '{OWNING_ORG_FK_NAME}'."
    )


def _request_in(org):
    """A request whose active org is already resolved, as OrgContextService caches it."""
    return SimpleNamespace(_rbac_active_org_id=org.id)


@pytest.fixture
def agent_definitions(acme, beta):
    own = AgentDefinition.objects.create(org=acme, name="acme-agent", instructions="x")
    foreign = AgentDefinition.objects.create(org=beta, name="beta-agent", instructions="x")
    yield own, foreign


@pytest.fixture
def surfaces(acme, beta):
    own = Surface.objects.create(org=acme, name="acme-surface")
    foreign = Surface.objects.create(org=beta, name="beta-surface")
    yield own, foreign


@pytest.mark.django_db
class TestAgentsAppModels:
    def test_agent_definition_queryset_excludes_other_org(self, acme, agent_definitions):
        own, foreign = agent_definitions

        visible_ids = set(
            org_visible_queryset(AgentDefinition, acme.id).values_list("id", flat=True)
        )

        assert own.id in visible_ids
        assert foreign.id not in visible_ids

    def test_surface_queryset_excludes_other_org(self, acme, surfaces):
        own, foreign = surfaces

        visible_ids = set(org_visible_queryset(Surface, acme.id).values_list("id", flat=True))

        assert own.id in visible_ids
        assert foreign.id not in visible_ids

    def test_surface_q_filters_on_org(self, acme, surfaces):
        own, foreign = surfaces

        visible = Surface.objects.filter(org_visible_q(Surface, acme.id))

        assert list(visible) == [own]


class _SurfaceRefSerializer(serializers.Serializer):
    surface = OrgVisiblePrimaryKeyRelatedField(queryset=Surface.objects.all())


class _SurfaceStrictRefSerializer(serializers.Serializer):
    surface = OrgScopedPrimaryKeyRelatedField(queryset=Surface.objects.all())


@pytest.mark.django_db
@pytest.mark.parametrize("serializer_class", [_SurfaceRefSerializer, _SurfaceStrictRefSerializer])
class TestRelatedFieldOnAgentsAppModel:
    def test_own_org_pk_accepted(self, serializer_class, acme, surfaces):
        own, _ = surfaces
        serializer = serializer_class(
            data={"surface": own.id}, context={"request": _request_in(acme)}
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["surface"] == own

    def test_other_org_pk_rejected_as_nonexistent(self, serializer_class, acme, surfaces):
        _, foreign = surfaces
        serializer = serializer_class(
            data={"surface": foreign.id}, context={"request": _request_in(acme)}
        )

        assert not serializer.is_valid()
        assert serializer.errors["surface"][0].code == "does_not_exist"


@pytest.mark.django_db
class TestExistingRulesUnchanged:
    def test_is_custom_hybrid_shows_built_ins_and_own_org_only(self, acme, beta):
        built_in = LLMModel.objects.create(name="xorg-built-in", is_custom=False, org=None)
        own = LLMModel.objects.create(name="xorg-acme", is_custom=True, org=acme)
        foreign = LLMModel.objects.create(name="xorg-beta", is_custom=True, org=beta)

        visible_ids = set(org_visible_queryset(LLMModel, acme.id).values_list("id", flat=True))

        assert {built_in.id, own.id} <= visible_ids
        assert foreign.id not in visible_ids

    def test_built_in_hybrid_shows_built_ins_and_own_org_only(self, acme, beta):
        def make_tool(name, org, built_in):
            return PythonCodeTool.objects.create(
                name=name,
                description="d",
                python_code=PythonCode.objects.create(code="def main(): pass"),
                built_in=built_in,
                org=org,
            )

        built_in = make_tool("xorg-built-in-tool", None, True)
        own = make_tool("xorg-acme-tool", acme, False)
        foreign = make_tool("xorg-beta-tool", beta, False)

        visible_ids = set(
            org_visible_queryset(PythonCodeTool, acme.id).values_list("id", flat=True)
        )

        assert {built_in.id, own.id} <= visible_ids
        assert foreign.id not in visible_ids

    def test_strict_org_model_shows_own_org_only(self, acme, beta):
        own = Label.objects.create(name="xorg-acme-label", org=acme)
        foreign = Label.objects.create(name="xorg-beta-label", org=beta)

        visible_ids = set(org_visible_queryset(Label, acme.id).values_list("id", flat=True))

        assert own.id in visible_ids
        assert foreign.id not in visible_ids


@pytest.mark.django_db
class TestModelWithoutOwningOrgFailsClosed:
    def test_org_visible_q_raises(self, acme):
        with pytest.raises(ImproperlyConfigured):
            org_visible_q(Provider, acme.id)

    def test_org_visible_queryset_raises(self, acme):
        with pytest.raises(ImproperlyConfigured):
            org_visible_queryset(Provider, acme.id)

    def test_related_field_raises(self, acme):
        provider = Provider.objects.create(name="xorg-provider")

        class ProviderRefSerializer(serializers.Serializer):
            provider = OrgVisiblePrimaryKeyRelatedField(queryset=Provider.objects.all())

        serializer = ProviderRefSerializer(
            data={"provider": provider.id}, context={"request": _request_in(acme)}
        )

        with pytest.raises(ImproperlyConfigured):
            serializer.is_valid()
