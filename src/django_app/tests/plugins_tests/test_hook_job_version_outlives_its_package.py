"""A hook job keeps the version its attempt was made to as text, so its result still brings the
grant to that version after the package row is gone (an upgrade's completion deletes it)."""

import pytest
from plugins.models import GrantState, HookJobKind, HookJobState, PluginGrant, PluginHookJob

from tests.plugins_tests.upgrade_fixtures import active_grant

pytestmark = [pytest.mark.django_db]


def _claim(node_client, job):
    response = node_client.post(f"/api/plugin-nodes/self/hook-jobs/{job.pk}/claim/")
    assert response.status_code == 200, response.content
    job.refresh_from_db()
    return job


def _succeed(node_client, job):
    return node_client.post(
        f"/api/plugin-nodes/self/hook-jobs/{job.pk}/result/",
        {"attempt": job.attempt, "outcome": "succeeded", "duration_ms": 10},
        format="json",
    )


def _package_gone(job):
    # What deleting the package does to the job: its foreign key is SET_NULL.
    PluginHookJob.objects.filter(pk=job.pk).update(package=None)


def test_an_install_job_s_result_after_its_package_went_brings_the_grant_to_the_claimed_version(
    weather_backend, superadmin_client, acme, node_client
):
    plugin = weather_backend(hooks={"install": True})
    assert superadmin_client.post(
        "/api/admin/plugins/weather/grants/", {"organization_id": acme.pk}, format="json"
    ).status_code == 201
    job = _claim(node_client, PluginHookJob.objects.get(kind=HookJobKind.INSTALL))
    assert job.package_version == plugin.current_package.version
    _package_gone(job)

    assert _succeed(node_client, job).status_code == 204

    grant = PluginGrant.objects.get(pk=job.grant_id)
    assert (grant.state, grant.installed_version) == (GrantState.ACTIVE, plugin.current_package.version)


def test_an_upgrade_job_s_result_after_its_package_went_brings_the_grant_to_the_claimed_version(
    weather_backend, superadmin, acme, node_client
):
    plugin = weather_backend(hooks={"upgrade": True})
    grant = active_grant(plugin, acme, superadmin, version="0.1.0")
    PluginGrant.objects.filter(pk=grant.pk).update(state=GrantState.UPGRADING)
    job = PluginHookJob.objects.create(
        plugin=plugin,
        grant=grant,
        organization_id=acme.pk,
        organization_name=acme.name,
        kind=HookJobKind.UPGRADE,
        package=plugin.current_package,
        timeout_seconds=30,
    )
    job = _claim(node_client, job)
    _package_gone(job)

    assert _succeed(node_client, job).status_code == 204

    grant.refresh_from_db()
    job.refresh_from_db()
    assert (grant.installed_version, job.state) == (plugin.current_package.version, HookJobState.SUCCEEDED)
