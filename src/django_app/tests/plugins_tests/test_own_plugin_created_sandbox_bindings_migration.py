"""plugins 0013 records the venvs and custom libraries a plugin created before they were ownable
as the plugin's, matching each to the plugin's activity event for its create request.

Invariants: a binding without an author created just before a plugin's create event in the same
organization becomes owned by that plugin's grant there; a binding a person created, one in
another organization, one outside the window, one matched only by an event written before the
grant, and one an event cannot tell apart from another binding stay unowned; running it again
adds nothing.
"""

from datetime import timedelta
from functools import cache
from importlib import import_module

import pytest
from django.contrib.contenttypes.models import ContentType
from django.db.migrations.loader import MigrationLoader
from django.utils import timezone
from plugins.models import (
    ActivityAction,
    ActorKind,
    GrantState,
    Plugin,
    PluginActivityEvent,
    PluginOwnedResource,
    PluginState,
)
from proxies.sandbox.models import SandboxCustomLibraryBinding, SandboxVenvBinding

MIGRATION = ("plugins", "0013_own_plugin_created_sandbox_bindings")
migration = import_module(f"{MIGRATION[0]}.migrations.{MIGRATION[1]}")

pytestmark = [pytest.mark.django_db]

CREATE_ROUTES = {SandboxVenvBinding: "api/venvs/", SandboxCustomLibraryBinding: "api/custom-libraries/"}
START = timezone.now() - timedelta(days=30)


@pytest.fixture
def weather(grant_to, acme):
    plugin = Plugin.objects.create(identifier="weather", name="Weather", description="d", state=PluginState.RUNNING)
    grant = grant_to(plugin, acme)
    _set_created_at(grant, START - timedelta(days=1))
    return grant


def _set_created_at(row, created_at):
    type(row).objects.filter(pk=row.pk).update(created_at=created_at)


def _binding(model, organization, at_seconds, created_by=None):
    binding = model.objects.create(org=organization, resource_id=f"r-{at_seconds}", created_by=created_by)
    _set_created_at(binding, START + timedelta(seconds=at_seconds))
    return binding


def _create_event(model, organization, at_seconds, identifier="weather", on_behalf_of=None, **changes):
    fields = {
        "plugin_identifier": identifier,
        "organization_id": organization.pk,
        "actor_kind": ActorKind.PLUGIN,
        "actor_label": "Weather (plugin)",
        "on_behalf_of_user": on_behalf_of,
        "action": ActivityAction.API_REQUEST,
        "request_method": "POST",
        "request_path": f"/{CREATE_ROUTES[model]}",
        "request_route": CREATE_ROUTES[model],
        "response_status": 201,
    }
    event = PluginActivityEvent.objects.create(**{**fields, **changes})
    _set_created_at(event, START + timedelta(seconds=at_seconds))
    return event


def _created(model, organization, at_seconds, **event_changes):
    """A binding and the plugin's create event for it 0.05 s later, as the old code left them."""
    binding = _binding(model, organization, at_seconds)
    _create_event(model, organization, at_seconds + 0.05, **event_changes)
    return binding


@cache
def _apps_at_the_migration():
    """The models as the migration sees them. The database stays at the latest schema, which
    is fine while plugins 0013 and proxies 0004 are the latest migrations of their apps."""
    return MigrationLoader(None, ignore_no_migrations=True).project_state(MIGRATION, at_end=True).apps


def _run():
    migration.own_plugin_created_bindings(_apps_at_the_migration(), None)


def _owners():
    return {
        (row.content_type.model_class(), row.object_id): (row.grant_id, row.org_id, row.plugin_identifier, row.on_behalf_of_id)
        for row in PluginOwnedResource.objects.select_related("content_type")
    }


@pytest.mark.parametrize("model", [SandboxVenvBinding, SandboxCustomLibraryBinding])
def test_a_binding_the_plugin_created_becomes_its_grant_s_in_its_organization(model, weather, acme, admin_acme):
    binding = _created(model, acme, 0, on_behalf_of=admin_acme)

    _run()

    assert _owners() == {(model, binding.pk): (weather.pk, acme.pk, "weather", admin_acme.pk)}


def test_the_plugin_s_creates_one_after_another_each_claim_their_own_binding(weather, acme):
    bindings = [_created(SandboxVenvBinding, acme, seconds) for seconds in (0, 0.2, 0.4)]

    _run()

    assert set(_owners()) == {(SandboxVenvBinding, binding.pk) for binding in bindings}


def test_a_venv_event_never_claims_a_custom_library(weather, acme):
    _binding(SandboxCustomLibraryBinding, acme, 0)
    _create_event(SandboxVenvBinding, acme, 0.05)

    _run()

    assert _owners() == {}


def test_a_binding_a_person_created_stays_unowned(weather, acme, admin_acme):
    _binding(SandboxVenvBinding, acme, 0, created_by=admin_acme)
    _create_event(SandboxVenvBinding, acme, 0.05)

    _run()

    assert _owners() == {}


def test_a_binding_in_another_organization_stays_unowned(weather, acme, beta):
    _binding(SandboxVenvBinding, beta, 0)
    _create_event(SandboxVenvBinding, acme, 0.05)

    _run()

    assert _owners() == {}


def test_an_event_in_an_organization_without_the_plugin_s_grant_claims_nothing(weather, beta):
    _created(SandboxVenvBinding, beta, 0)

    _run()

    assert _owners() == {}


def test_an_event_before_the_grant_claims_nothing(weather, acme):
    _set_created_at(weather, START + timedelta(seconds=1))
    _created(SandboxVenvBinding, acme, 0)

    _run()

    assert _owners() == {}


@pytest.mark.parametrize(
    ("event_seconds", "owned"),
    [(1.9, True), (2.0, False)],
)
def test_only_a_binding_created_within_the_window_before_the_event_is_claimed(weather, acme, event_seconds, owned):
    binding = _binding(SandboxVenvBinding, acme, 0)
    _create_event(SandboxVenvBinding, acme, event_seconds)

    _run()

    assert ((SandboxVenvBinding, binding.pk) in _owners()) is owned


def test_an_authorless_binding_in_the_window_is_claimed_once_the_plugin_s_own_is_gone(weather, acme):
    # The accepted false claim: with the plugin's binding deleted, nothing tells the
    # organization's binding apart from it.
    _binding(SandboxVenvBinding, acme, 0).delete()
    organization_s = _binding(SandboxVenvBinding, acme, 0.5)
    _create_event(SandboxVenvBinding, acme, 1)

    _run()

    assert (SandboxVenvBinding, organization_s.pk) in _owners()


def test_a_binding_created_after_the_event_is_not_its(weather, acme):
    _create_event(SandboxVenvBinding, acme, 0)
    _binding(SandboxVenvBinding, acme, 0.05)

    _run()

    assert _owners() == {}


@pytest.mark.parametrize("changes", [{"response_status": 400}, {"request_method": "PATCH"}, {"target_id": "7"}])
def test_an_event_that_is_not_an_unrecorded_create_claims_nothing(weather, acme, changes):
    _created(SandboxVenvBinding, acme, 0, **changes)

    _run()

    assert _owners() == {}


def test_overlapping_creates_leave_both_bindings_unowned(weather, acme):
    # Another caller without an author (the system API key) created a venv during the
    # plugin's request: nothing tells which of the two is the plugin's.
    _binding(SandboxVenvBinding, acme, 0)
    _binding(SandboxVenvBinding, acme, 0.01)
    _create_event(SandboxVenvBinding, acme, 0.05)

    _run()

    assert _owners() == {}


def test_a_binding_already_owned_is_left_as_it_is(weather, acme):
    binding = _created(SandboxVenvBinding, acme, 0)
    PluginOwnedResource.objects.create(
        org=acme,
        grant=weather,
        plugin_identifier="weather",
        content_type=ContentType.objects.get_for_model(SandboxVenvBinding),
        object_id=binding.pk,
    )

    _run()

    assert PluginOwnedResource.objects.count() == 1


def test_an_owned_binding_in_the_window_leaves_the_unowned_one_the_only_candidate(weather, acme):
    already_owned = _binding(SandboxVenvBinding, acme, 0)
    PluginOwnedResource.objects.create(
        org=acme,
        grant=weather,
        plugin_identifier="weather",
        content_type=ContentType.objects.get_for_model(SandboxVenvBinding),
        object_id=already_owned.pk,
    )
    unowned = _binding(SandboxVenvBinding, acme, 0.5)
    _create_event(SandboxVenvBinding, acme, 1)

    _run()

    assert set(_owners()) == {(SandboxVenvBinding, already_owned.pk), (SandboxVenvBinding, unowned.pk)}
    assert PluginOwnedResource.objects.count() == 2


def test_running_it_twice_adds_nothing_the_second_time(weather, acme):
    bindings = [_created(SandboxVenvBinding, acme, seconds) for seconds in (0, 0.2)]
    _run()
    first = _owners()

    _run()

    assert _owners() == first
    assert PluginOwnedResource.objects.count() == len(bindings)
