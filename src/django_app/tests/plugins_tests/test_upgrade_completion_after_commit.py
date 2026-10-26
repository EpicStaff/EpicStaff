"""What an upgrade's completion does to the served frontend once it commits: three steps, each on
its own, so a failure in one leaves the others done."""

import pytest
from plugins.models import Plugin, PluginState
from plugins.packages.spa_publisher import CURRENT_LINK, MAINTENANCE_FLAG, SpaPublisher

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    advance_url,
    backup_body,
    newer,
    send_report,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]


@pytest.fixture
def migrating(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    """Weather's upgrade to 0.7.0 in its migrating stage, the plugin in maintenance."""
    upgrade = upgrade_of(newer())
    with django_capture_on_commit_callbacks(execute=True):
        assert node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json").status_code == 204
    body = {"to": "migrations", "backup": backup_body(upgrade)}
    assert node_client.post(advance_url(upgrade.pk), body, format="json").status_code == 204
    return upgrade


def _complete(node_client, weather, capture):
    with capture(execute=True):
        send_report(node_client, weather, observed_version="0.7.0")


def test_a_switch_that_fails_still_ends_maintenance_and_keeps_the_version_still_served(
    migrating, weather, node_client, spa_root, monkeypatch, django_capture_on_commit_callbacks
):
    (spa_root / "weather" / "0.5.0").mkdir()
    assert (spa_root / "weather" / MAINTENANCE_FLAG).exists()

    def refuse(self, identifier, version):
        raise OSError("the volume is read-only")

    monkeypatch.setattr(SpaPublisher, "switch_current", refuse)

    _complete(node_client, weather, django_capture_on_commit_callbacks)

    assert Plugin.objects.get(pk=weather.pk).state == PluginState.RUNNING
    assert not (spa_root / "weather" / MAINTENANCE_FLAG).exists()
    assert (spa_root / "weather" / CURRENT_LINK).readlink().name == "0.6.0"
    assert sorted(entry.name for entry in (spa_root / "weather").iterdir() if not entry.is_symlink()) == [
        "0.6.0",
        "0.7.0",
    ]


def test_a_flag_that_cannot_be_removed_still_serves_the_new_version_and_prunes_the_old(
    migrating, weather, node_client, spa_root, monkeypatch, django_capture_on_commit_callbacks
):
    def refuse(self, identifier, on):
        raise OSError("the volume is read-only")

    monkeypatch.setattr(SpaPublisher, "set_maintenance", refuse)

    _complete(node_client, weather, django_capture_on_commit_callbacks)

    assert (spa_root / "weather" / CURRENT_LINK).readlink().name == "0.7.0"
    assert not (spa_root / "weather" / "0.6.0").exists()
