"""Settling every grant of a plugin during an upgrade costs the same number of queries whatever
the number of grants: maintenance, completion (an upgrade hook job per grant) and cancel."""

import json
from collections.abc import Callable
from functools import partial

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from plugins.lifecycle.upgrade_service import PluginUpgradeService, parse_upgrade_advance
from plugins.models import GrantState, HookJobKind, HookJobState, Plugin, PluginGrant, PluginHookJob
from rbac.models import Organization
from src.shared.models.plugin_nodes import PlacementReport, UpgradeAdvance

from tests.plugins_tests.conftest import mark_running
from tests.plugins_tests.upgrade_fixtures import (
    active_grant,
    backup_body,
    database_ready,
    placement_of,
    start_upgrade,
    upload,
    weather_manifest,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]


def _queries(run) -> int:
    with CaptureQueriesContext(connection) as captured:
        run()
    return len(captured.captured_queries)


def _advance(to: str, backup: dict | None = None) -> Callable[[], UpgradeAdvance]:
    body = json.dumps({"to": to, **({"backup": backup} if backup else {})}).encode()
    return partial(parse_upgrade_advance, body)


@pytest.fixture
def counts(database_plugin, installation, superadmin, plugin_node, django_capture_on_commit_callbacks):
    """Factory → the queries of maintenance, completion and a cancel, for a plugin with `grants`."""

    def _measure(identifier: str, grants: int) -> dict[str, int]:
        plugin = mark_running(database_plugin(id=identifier, version="0.6.0"))
        database_ready(plugin)
        for index in range(grants):
            active_grant(plugin, Organization.objects.create(name=f"{identifier} {index}"), superadmin)
        service = PluginUpgradeService()

        def upgrade_to(version: str):
            package = upload(installation, superadmin, weather_manifest(version, id=identifier, hooks={"upgrade": True}))
            return start_upgrade(installation, superadmin, package, django_capture_on_commit_callbacks)

        first = upgrade_to("0.7.0")
        measured = {"maintenance": _queries(lambda: service.advance(plugin_node, first.pk, _advance("maintenance")))}
        service.advance(plugin_node, first.pk, _advance("migrations", backup_body(first)))
        placement = placement_of(plugin)
        healthy = PlacementReport(
            placement_id=placement.pk,
            observed_state="running",
            observed_version="0.7.0",
            health="ok",
            restarts=0,
            applied_settings_revision=placement.settings_revision,
            applied_restart_generation=placement.restart_generation,
        )
        measured["completion"] = _queries(lambda: service.follow_report(plugin_node, placement.pk, healthy, timezone.now()))
        assert PluginGrant.objects.filter(plugin=plugin, state=GrantState.UPGRADING).count() == grants
        assert PluginHookJob.objects.filter(
            plugin=plugin, kind=HookJobKind.UPGRADE, state=HookJobState.PENDING
        ).count() == grants
        second = upgrade_to("0.8.0")
        service.advance(plugin_node, second.pk, _advance("maintenance"))
        measured["cancel"] = _queries(lambda: service.cancel(identifier, superadmin))
        assert Plugin.objects.get(pk=plugin.pk).current_package.version == "0.7.0"
        return measured

    return _measure


def test_the_queries_of_maintenance_completion_and_cancel_do_not_grow_with_the_grants(counts):
    one, ten, fifty = counts("weather", 1), counts("tides", 10), counts("winds", 50)

    assert one == ten == fifty, (one, ten, fifty)


def test_completion_restarts_the_series_of_a_job_that_was_failing_and_creates_the_missing_ones(
    database_plugin, installation, superadmin, plugin_node, django_capture_on_commit_callbacks
):
    plugin = mark_running(database_plugin(version="0.6.0", hooks={"upgrade": True}))
    database_ready(plugin)
    failing, fresh = (
        active_grant(plugin, Organization.objects.create(name=name), superadmin, version="0.5.0") for name in ("Failing", "Fresh")
    )
    PluginGrant.objects.filter(pk=failing.pk).update(state=GrantState.UPGRADING)
    waiting = PluginHookJob.objects.create(
        plugin=plugin,
        grant=failing,
        organization_id=failing.org_id,
        organization_name="Failing",
        kind=HookJobKind.UPGRADE,
        package=plugin.current_package,
        timeout_seconds=30,
        failures_in_series=2,
        next_attempt_at=timezone.now() + timezone.timedelta(hours=1),
    )
    package = upload(installation, superadmin, weather_manifest("0.7.0", hooks={"upgrade": True}))
    upgrade = start_upgrade(installation, superadmin, package, django_capture_on_commit_callbacks)
    service = PluginUpgradeService()
    service.advance(plugin_node, upgrade.pk, _advance("maintenance"))
    service.advance(plugin_node, upgrade.pk, _advance("migrations", backup_body(upgrade)))
    placement = placement_of(plugin)

    service.follow_report(
        plugin_node,
        placement.pk,
        PlacementReport(
            placement_id=placement.pk,
            observed_state="running",
            observed_version="0.7.0",
            health="ok",
            restarts=0,
            applied_settings_revision=placement.settings_revision,
            applied_restart_generation=placement.restart_generation,
        ),
        timezone.now(),
    )

    waiting.refresh_from_db()
    assert (waiting.failures_in_series, waiting.next_attempt_at) == (0, None)
    jobs = PluginHookJob.objects.filter(kind=HookJobKind.UPGRADE, state=HookJobState.PENDING)
    assert sorted(jobs.values_list("grant_id", flat=True)) == sorted([failing.pk, fresh.pk])
    assert set(PluginGrant.objects.filter(pk__in=[failing.pk, fresh.pk]).values_list("state", flat=True)) == {
        GrantState.UPGRADING
    }
