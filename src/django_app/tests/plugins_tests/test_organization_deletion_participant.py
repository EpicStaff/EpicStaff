"""The plugins app's part in deleting an organization."""

import pytest
from plugins.lifecycle.grant_service import PluginGrantService
from plugins.models import (
    ActivityAction,
    GrantState,
    HookJobKind,
    HookJobState,
    PluginActivityEvent,
    PluginGrant,
    PluginHookJob,
    PluginOwnedResource,
    PluginRolePermission,
    PluginServiceAccount,
    PluginServiceAccountKey,
)
from plugins.organization_deletion import ORGANIZATION_DELETED, PluginsOrganizationDeletion
from rbac.governance.delete_collector import build_collector
from rbac.governance.delete_resource_names import known_excluded_resource_labels, known_resource_names
from rbac.governance.organization_deletion import participants
from rbac.governance.organizations import OrganizationManagementService
from tables.services.organization_deletion import TablesOrganizationDeletion

from tests.plugins_tests.suspension_helpers import flow, own, secret_row

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

HOOKS = {"install": True, "org_removed": True}


@pytest.fixture(autouse=True)
def no_storage_calls(mocker):
    """The organization's storage is a network dependency."""
    backend = mocker.MagicMock()
    backend.list_all_objects.return_value = []
    return mocker.patch("tables.services.organization_deletion.get_storage_backend", return_value=backend)


@pytest.fixture
def actor(superadmin):
    superadmin.is_superadmin = True
    superadmin.save(update_fields=["is_superadmin"])
    return superadmin


@pytest.fixture
def weather(weather_backend):
    return weather_backend(hooks=HOOKS)


@pytest.fixture
def cobalt(db, acme):
    """The organization deleted; Acme stays, as one active organization must."""
    from rbac.models import Organization

    return Organization.objects.create(name="Cobalt")


@pytest.fixture
def cobalt_grant(weather, superadmin, cobalt, service_account_key, make_custom_role):
    """Weather in Cobalt with its install hook not run yet, a key, a role's actions and a flow."""
    grant = PluginGrantService().grant("weather", cobalt.pk, superadmin)
    service_account_key(weather, cobalt)
    PluginRolePermission.objects.create(grant=grant, role=make_custom_role(cobalt, "Forecasters"), permissions=1)
    own(flow(cobalt, "Weather forecast"), grant)
    own(secret_row(cobalt, "Weather · LLM key"), grant)
    return grant


def _delete(actor, organization, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        return OrganizationManagementService().delete_organization(
            actor, organization.pk, verification_phrase=f"delete-{organization.name}"
        )


def test_the_participant_is_registered_once_after_the_tables_one():
    kinds = [type(participant) for participant in participants()]

    assert kinds.count(PluginsOrganizationDeletion) == 1
    assert kinds.index(TablesOrganizationDeletion) < kinds.index(PluginsOrganizationDeletion)


def test_the_preview_names_the_grants_and_the_plugin_data(cobalt_grant, actor, cobalt):
    report = OrganizationManagementService().preview_delete(actor, cobalt.pk)

    assert report.affected_resources["plugin_grants"] == 1
    assert report.affected_resources["plugin_data"] == 1


def test_the_delete_asks_the_plugin_to_delete_its_data_and_leaves_nothing_of_the_grant(
    cobalt_grant, actor, cobalt, django_capture_on_commit_callbacks, log_messages
):
    preview = OrganizationManagementService().preview_delete(actor, cobalt.pk)
    cobalt_id, cobalt_name = cobalt.pk, cobalt.name
    PluginActivityEvent.objects.create(
        plugin_identifier="weather", organization_id=cobalt_id, actor_kind="platform", actor_label="Platform", action="grant_created"
    )

    report = _delete(actor, cobalt, django_capture_on_commit_callbacks)

    assert report.affected_resources == preview.affected_resources
    job = PluginHookJob.objects.get(kind=HookJobKind.ORG_REMOVED)
    assert (job.organization_id, job.organization_name, job.grant_id, job.state) == (
        cobalt_id,
        cobalt_name,
        None,
        HookJobState.PENDING,
    )
    install = PluginHookJob.objects.get(kind=HookJobKind.INSTALL)
    assert (install.state, install.error) == (HookJobState.FAILED, ORGANIZATION_DELETED)
    for model in (PluginGrant, PluginServiceAccount, PluginServiceAccountKey, PluginRolePermission, PluginOwnedResource):
        assert not model.objects.exists(), model
    assert PluginActivityEvent.objects.filter(organization_id=cobalt_id).exists()
    assert any(
        message == f"plugins.organization_deleted org={cobalt_id} grants=1 data_removals=1" for message in log_messages
    )


def test_an_unfinished_job_for_the_organization_is_reused(cobalt_grant, actor, cobalt, weather, django_capture_on_commit_callbacks):
    earlier = PluginHookJob.objects.create(
        plugin=weather,
        organization_id=cobalt.pk,
        organization_name="Cobalt before",
        kind=HookJobKind.ORG_REMOVED,
        state=HookJobState.FAILED,
        timeout_seconds=60,
    )

    _delete(actor, cobalt, django_capture_on_commit_callbacks)

    assert list(PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).values_list("pk", flat=True)) == [earlier.pk]


def test_a_grant_being_purged_keeps_its_data_removal_running(
    cobalt_grant, actor, cobalt, superadmin_client, django_capture_on_commit_callbacks
):
    response = superadmin_client.delete(
        f"/api/admin/plugins/weather/grants/{cobalt_grant.pk}/", {"verification_phrase": f"purge-weather-{cobalt.name}"}, format="json"
    )
    assert response.status_code == 202, response.content
    pending = PluginHookJob.objects.get(kind=HookJobKind.ORG_REMOVED)

    _delete(actor, cobalt, django_capture_on_commit_callbacks)

    pending.refresh_from_db()
    assert (pending.state, pending.grant_id) == (HookJobState.PENDING, None)
    assert PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).count() == 1


def test_a_plugin_without_the_hook_holds_no_data_and_gets_no_job(weather_backend, superadmin, cobalt, actor, django_capture_on_commit_callbacks):
    weather_backend(hooks={"install": False})
    PluginGrantService().grant("weather", cobalt.pk, superadmin)

    assert "plugin_data" not in OrganizationManagementService().preview_delete(actor, cobalt.pk).affected_resources
    _delete(actor, cobalt, django_capture_on_commit_callbacks)

    assert not PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED).exists()


def test_a_grant_being_purged_whose_own_data_removal_succeeded_is_not_counted_again(
    cobalt_grant, weather, cobalt, actor
):
    PluginGrant.objects.filter(pk=cobalt_grant.pk).update(state=GrantState.PURGING)
    PluginHookJob.objects.create(
        plugin=weather,
        grant=cobalt_grant,
        organization_id=cobalt.pk,
        kind=HookJobKind.ORG_REMOVED,
        state=HookJobState.SUCCEEDED,
        timeout_seconds=60,
    )

    assert "plugin_data" not in OrganizationManagementService().preview_delete(actor, cobalt.pk).affected_resources


def test_an_earlier_grant_s_finished_data_removal_does_not_cover_the_grant_now(cobalt_grant, weather, cobalt, actor):
    PluginHookJob.objects.create(
        plugin=weather,
        organization_id=cobalt.pk,
        kind=HookJobKind.ORG_REMOVED,
        state=HookJobState.SUCCEEDED,
        timeout_seconds=60,
    )

    assert OrganizationManagementService().preview_delete(actor, cobalt.pk).affected_resources["plugin_data"] == 1


@pytest.mark.parametrize("own_job", [None, HookJobState.SUCCEEDED, HookJobState.FAILED])
@pytest.mark.parametrize("grant_state", [GrantState.ACTIVE, GrantState.PURGING])
def test_the_delete_asks_for_as_many_data_removals_as_its_preview_counted(
    cobalt_grant, weather, cobalt, actor, django_capture_on_commit_callbacks, grant_state, own_job
):
    PluginGrant.objects.filter(pk=cobalt_grant.pk).update(state=grant_state)
    if own_job is not None:
        PluginHookJob.objects.create(
            plugin=weather,
            grant=cobalt_grant,
            organization_id=cobalt.pk,
            kind=HookJobKind.ORG_REMOVED,
            state=own_job,
            timeout_seconds=60,
        )
    previewed = OrganizationManagementService().preview_delete(actor, cobalt.pk).affected_resources.get("plugin_data", 0)

    _delete(actor, cobalt, django_capture_on_commit_callbacks)

    # The jobs that stand for the organization's data once it is gone: new or reused ones.
    standing = PluginHookJob.objects.filter(
        kind=HookJobKind.ORG_REMOVED, organization_id=cobalt.pk, state__in=(HookJobState.PENDING, HookJobState.FAILED)
    )
    assert standing.count() == previewed


def test_a_count_that_fails_counts_nothing(cobalt_grant, cobalt, mocker):
    mocker.patch("plugins.organization_deletion.grants_needing_a_job", side_effect=RuntimeError("down"))

    assert PluginsOrganizationDeletion().count_external_artifacts(cobalt) == {}


def test_every_plugins_label_the_cascade_reaches_is_mapped_or_excluded(cobalt_grant, cobalt, log_messages):
    collector = build_collector(cobalt)
    labels = {model._meta.label for model in collector.data} | {
        queryset.model._meta.label for queryset in collector.fast_deletes
    }
    plugin_labels = {label for label in labels if label.startswith("plugins.")}

    assert plugin_labels
    assert plugin_labels <= set(known_resource_names()) | set(known_excluded_resource_labels())
    assert not any("unmapped model label plugins." in message for message in log_messages)


def test_the_delete_works_while_plugins_are_off(cobalt_grant, actor, cobalt, settings, django_capture_on_commit_callbacks):
    settings.PLUGINS_ENABLED = False

    _delete(actor, cobalt, django_capture_on_commit_callbacks)

    assert not PluginGrant.objects.exists()
    assert PluginHookJob.objects.filter(kind=HookJobKind.ORG_REMOVED, state=HookJobState.PENDING).count() == 1


def test_a_deleted_organization_s_events_show_only_to_a_superadmin(
    cobalt_grant, actor, cobalt, superadmin_client, client_as, admin_acme, acme, django_capture_on_commit_callbacks
):
    cobalt_id = cobalt.pk
    _delete(actor, cobalt, django_capture_on_commit_callbacks)
    PluginActivityEvent.objects.create(
        plugin_identifier="weather",
        organization_id=cobalt_id,
        actor_kind="platform",
        actor_label="Platform",
        action=ActivityAction.ORG_REMOVED_HOOK_SUCCEEDED,
    )
    org_client = client_as(admin_acme)
    org_client.credentials(HTTP_X_ORGANIZATION_ID=str(acme.pk))

    admin_rows = superadmin_client.get(f"/api/admin/plugins/weather/activity/?organization_id={cobalt_id}").json()["results"]
    org_rows = org_client.get("/api/plugins/activity/").json()["results"]

    assert ActivityAction.ORG_REMOVED_HOOK_SUCCEEDED in {row["action"] for row in admin_rows}
    assert all(row["action"] != ActivityAction.ORG_REMOVED_HOOK_SUCCEEDED for row in org_rows)
