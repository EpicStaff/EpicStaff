"""The node's `advance` request: an unknown upgrade answers 404 and a closed one 409 before the
body is read, and a backup recorded with another sha256 never lets the migrations run."""

import pytest
from plugins.models import PluginDatabaseBackup, PluginUpgrade, UpgradeStage

from tests.plugins_tests.upgrade_fixtures import (  # noqa: F401 (fixtures)
    advance_url,
    backup_body,
    newer,
    send_report,
    upgrade_of,
    weather,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

NOT_A_REQUEST = {"to": "somewhere"}


@pytest.fixture
def in_maintenance(weather, newer, upgrade_of, node_client, django_capture_on_commit_callbacks):
    upgrade = upgrade_of(newer())
    with django_capture_on_commit_callbacks(execute=True):
        assert node_client.post(advance_url(upgrade.pk), {"to": "maintenance"}, format="json").status_code == 204
    upgrade.refresh_from_db()
    return upgrade


def _code(response):
    return response.status_code, response.json()["code"]


def test_an_unknown_upgrade_answers_404_whatever_the_body(weather, node_client):
    assert _code(node_client.post(advance_url(999999), NOT_A_REQUEST, format="json")) == (404, "upgrade_not_found")


def test_a_closed_upgrade_answers_409_whatever_the_body(in_maintenance, node_client):
    PluginUpgrade.objects.filter(pk=in_maintenance.pk).update(stage=UpgradeStage.CANCELLED)

    response = node_client.post(advance_url(in_maintenance.pk), NOT_A_REQUEST, format="json")

    assert _code(response) == (409, "upgrade_not_current")


def test_an_open_upgrade_with_a_body_that_is_not_a_request_answers_400(in_maintenance, node_client):
    response = node_client.post(advance_url(in_maintenance.pk), NOT_A_REQUEST, format="json")

    assert _code(response) == (400, "invalid_upgrade_advance")


def test_a_backup_recorded_with_another_sha256_answers_400_and_nothing_moves(in_maintenance, weather, node_client):
    send_report(node_client, weather, observed_state="stopped", health="unknown", backups=[backup_body(in_maintenance)])

    response = node_client.post(
        advance_url(in_maintenance.pk),
        {"to": "migrations", "backup": backup_body(in_maintenance, sha256="f" * 64)},
        format="json",
    )

    assert _code(response) == (400, "invalid_upgrade_advance")
    assert response.json()["errors"] == [
        {"loc": "advance.backup.sha256", "message": "is not the sha256 recorded for this backup"}
    ]
    in_maintenance.refresh_from_db()
    assert (in_maintenance.stage, in_maintenance.backup_id) == (UpgradeStage.MAINTENANCE, None)


def test_a_backup_a_report_marked_mismatched_answers_400(in_maintenance, weather, node_client):
    body = backup_body(in_maintenance)
    send_report(node_client, weather, observed_state="stopped", health="unknown", backups=[body])
    PluginDatabaseBackup.objects.filter(file_name=body["file_name"]).update(sha256_mismatch=True)

    response = node_client.post(advance_url(in_maintenance.pk), {"to": "migrations", "backup": body}, format="json")

    assert _code(response) == (400, "invalid_upgrade_advance")
    in_maintenance.refresh_from_db()
    assert in_maintenance.stage == UpgradeStage.MAINTENANCE


def test_the_backup_the_report_recorded_lets_the_migrations_run(in_maintenance, weather, node_client):
    body = backup_body(in_maintenance)
    send_report(node_client, weather, observed_state="stopped", health="unknown", backups=[body])

    assert node_client.post(advance_url(in_maintenance.pk), {"to": "migrations", "backup": body}, format="json").status_code == 204

    in_maintenance.refresh_from_db()
    assert in_maintenance.backup.file_name == body["file_name"]
