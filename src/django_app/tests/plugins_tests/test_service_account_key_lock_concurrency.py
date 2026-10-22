"""Minting and revoking a plugin's keys while one of its organizations is deleted: both finish.

The deletion locks the organization's grants, then deletes their service accounts and keys.
Every key path locks the plugin's grants before their accounts, so it waits for the deletion
instead of deadlocking with it, and a key it inserts is never left pointing at an account the
deletion removes. Two connections at once (`lock_concurrency`).
"""

import pytest
from plugins.development.development_runtime import DevelopmentRuntimeFileService
from plugins.development.development_targets import DevelopmentTargetService
from plugins.identity import service_account_keys
from plugins.models import PluginServiceAccountKey, ServiceAccountKeyPurpose
from plugins.nodes.runtime_credentials_service import RuntimeCredentialsService
from plugins.organization_deletion import PluginsOrganizationDeletion
from rbac.governance.organizations import OrganizationManagementService
from rbac.models import Organization

from tests.plugins_tests.conftest import mark_running
from tests.plugins_tests.lock_concurrency import Paused, Side, run_pair
from tests.plugins_tests.upgrade_fixtures import active_grant, placement_of

pytestmark = [
    pytest.mark.django_db(transaction=True),
    pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root", "development_mode"),
]


@pytest.fixture
def no_storage_calls(mocker):
    """An organization's deletion lists and deprovisions its storage: nothing to do here."""
    mocker.patch(
        "tables.services.organization_deletion.get_storage_backend"
    ).return_value.list_all_objects.return_value = []
    mocker.patch.object(OrganizationManagementService, "_deprovision_storage", lambda *args, **kwargs: None)


@pytest.fixture
def weather_in_two_organizations(database_plugin, acme, superadmin, no_storage_calls):
    """Weather running in Acme and Cobalt, with node and development keys in both.

    Acme stays: the last active organization cannot be deleted.
    """
    plugin = mark_running(database_plugin(id="weather"))
    cobalt = Organization.objects.create(name="Cobalt")
    for organization in (acme, cobalt):
        active_grant(plugin, organization, superadmin)
    service_account_keys.ServiceAccountKeyService().mint_for_plugin(plugin)
    service_account_keys.ServiceAccountKeyService().mint_development_keys(plugin)
    return plugin, cobalt


def _delete(organization, superadmin):
    return Side(
        "organization deletion",
        lambda: OrganizationManagementService().delete_organization(
            superadmin, organization.pk, verification_phrase=f"delete-{organization.name}"
        ),
    )


def _pause_the_deletion_after_its_sweep(monkeypatch) -> Paused:
    paused = Paused(PluginsOrganizationDeletion.sweep)
    monkeypatch.setattr(PluginsOrganizationDeletion, "sweep", lambda self, *args, **kwargs: paused(self, *args, **kwargs))
    return paused


def _pause_after_inserting_keys(monkeypatch) -> Paused:
    paused = Paused(service_account_keys._create_keys)
    monkeypatch.setattr(service_account_keys, "_create_keys", paused)
    return paused


def _working_keys(purpose: str) -> list[int]:
    return sorted(
        PluginServiceAccountKey.objects.filter(purpose=purpose, revoked_at__isnull=True, expires_at__isnull=True)
        .values_list("service_account__grant__org_id", flat=True)
    )


def test_stopping_development_while_an_organization_is_deleted_both_finish(
    weather_in_two_organizations, superadmin, acme, monkeypatch
):
    _, cobalt = weather_in_two_organizations
    paused = _pause_the_deletion_after_its_sweep(monkeypatch)

    run_pair(
        _delete(cobalt, superadmin),
        Side("stop development", lambda: DevelopmentTargetService().clear("weather", superadmin)),
        paused,
    )

    assert not Organization.objects.filter(pk=cobalt.pk).exists()
    assert _working_keys(ServiceAccountKeyPurpose.DEVELOPMENT) == []
    assert _working_keys(ServiceAccountKeyPurpose.NODE) == [acme.pk]


def test_a_runtime_file_download_while_an_organization_is_deleted_both_finish(
    weather_in_two_organizations, superadmin, acme, monkeypatch
):
    _, cobalt = weather_in_two_organizations
    paused = _pause_the_deletion_after_its_sweep(monkeypatch)
    download = Side("download", lambda: DevelopmentRuntimeFileService().issue("weather", superadmin))

    run_pair(_delete(cobalt, superadmin), download, paused)

    assert not Organization.objects.filter(pk=cobalt.pk).exists()
    assert list(download.result["service_accounts"]) == [str(acme.pk)]
    assert _working_keys(ServiceAccountKeyPurpose.DEVELOPMENT) == [acme.pk]


@pytest.mark.parametrize("purpose", [ServiceAccountKeyPurpose.DEVELOPMENT, ServiceAccountKeyPurpose.NODE])
def test_keys_inserted_before_an_organization_is_deleted_never_fail_the_deletion(
    weather_in_two_organizations, superadmin, acme, plugin_node, monkeypatch, purpose
):
    plugin, cobalt = weather_in_two_organizations
    paused = _pause_after_inserting_keys(monkeypatch)
    if purpose == ServiceAccountKeyPurpose.DEVELOPMENT:
        mint = Side("download", lambda: DevelopmentRuntimeFileService().issue("weather", superadmin))
    else:
        placement_id = placement_of(plugin).pk
        mint = Side("node credentials", lambda: RuntimeCredentialsService().credentials_for(plugin_node, placement_id))

    run_pair(mint, _delete(cobalt, superadmin), paused)

    assert not Organization.objects.filter(pk=cobalt.pk).exists()
    assert _working_keys(purpose) == [acme.pk]
