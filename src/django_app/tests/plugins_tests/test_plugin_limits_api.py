"""SuperAdmin limits of a plugin's backend: requested, platform maximum, overrides, effective."""

import pytest
from plugins.models import Plugin

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

LIMITS_URL = "/api/admin/plugins/weather/limits/"
DESIRED_STATE_URL = "/api/plugin-nodes/self/desired-state/"
REQUESTED = {"memory_mb": 256, "db_connections": 5, "statement_timeout_seconds": 10, "requests_per_minute": 120, "cpu_priority": "normal"}


@pytest.fixture
def maximums(settings):
    settings.PLUGINS_MAX_PROCESS_MEMORY_MB = "1024"
    settings.PLUGINS_MAX_DB_CONNECTIONS = "20"
    settings.PLUGINS_MAX_STATEMENT_TIMEOUT_SECONDS = "60"
    settings.PLUGINS_MAX_REQUESTS_PER_MINUTE = "600"
    return settings


@pytest.fixture
def weather(backend_plugin, maximums):
    return backend_plugin()


def _patch(client, **overrides):
    return client.patch(LIMITS_URL, {"overrides": overrides}, format="json")


def _desired_runtime(node_client):
    return node_client.get(DESIRED_STATE_URL).json()["placements"][0]["runtime"]


def test_limits_show_every_view(weather, superadmin_client):
    response = superadmin_client.get(LIMITS_URL)

    assert response.status_code == 200
    assert response.json() == {
        "requested": REQUESTED,
        "platform_max": {"memory_mb": 1024, "db_connections": 20, "statement_timeout_seconds": 60, "requests_per_minute": 600},
        "overrides": {},
        "effective": REQUESTED,
        "enforced": {
            "memory_mb": True,
            "cpu_priority": True,
            "db_connections": False,
            "statement_timeout_seconds": False,
            "requests_per_minute": True,
        },
        "has_database": False,
    }


def test_a_plugin_with_a_database_has_its_database_limits_enforced(database_plugin, maximums, superadmin_client):
    database_plugin()

    body = superadmin_client.get(LIMITS_URL).json()

    assert body["has_database"] is True
    assert body["enforced"] == {
        "memory_mb": True,
        "cpu_priority": True,
        "db_connections": True,
        "statement_timeout_seconds": True,
        "requests_per_minute": True,
    }


def test_lowering_a_database_limit_answers_with_the_new_effective_value(database_plugin, maximums, superadmin_client):
    database_plugin()

    response = _patch(superadmin_client, statement_timeout_seconds=5)

    assert response.status_code == 200
    assert (response.json()["effective"]["statement_timeout_seconds"], response.json()["has_database"]) == (5, True)


def test_a_manifest_without_limits_gets_the_platform_defaults_capped_by_the_maximums(backend_plugin, maximums, superadmin_client):
    maximums.PLUGINS_MAX_PROCESS_MEMORY_MB = "128"
    backend_plugin(limits=None)

    requested = superadmin_client.get(LIMITS_URL).json()["requested"]

    assert requested == {"memory_mb": 128, "db_connections": 5, "statement_timeout_seconds": 30, "requests_per_minute": 120, "cpu_priority": "normal"}


@pytest.mark.parametrize(
    ("limits", "expected"),
    [
        ({}, {"memory_mb": 256, "db_connections": 5, "statement_timeout_seconds": 30, "requests_per_minute": 120, "cpu_priority": "normal"}),
        ({"memory_mb": 512}, {"memory_mb": 512, "db_connections": 5, "statement_timeout_seconds": 30, "requests_per_minute": 120, "cpu_priority": "normal"}),
        (
            {"cpu_priority": "low", "db_connections": None, "requests_per_minute": 30},
            {"memory_mb": 256, "db_connections": 5, "statement_timeout_seconds": 30, "requests_per_minute": 30, "cpu_priority": "low"},
        ),
    ],
    ids=["empty", "one limit", "some limits and a null"],
)
def test_each_limit_the_manifest_leaves_out_gets_the_platform_default(backend_plugin, maximums, superadmin_client, limits, expected):
    backend_plugin(limits=limits)

    assert superadmin_client.get(LIMITS_URL).json()["requested"] == expected


def test_a_default_is_capped_by_a_lower_maximum_but_a_declared_limit_is_shown_as_asked(backend_plugin, maximums, superadmin_client):
    backend_plugin(limits={"memory_mb": 512})
    maximums.PLUGINS_MAX_PROCESS_MEMORY_MB = "300"
    maximums.PLUGINS_MAX_REQUESTS_PER_MINUTE = "60"

    body = superadmin_client.get(LIMITS_URL).json()

    assert (body["requested"]["memory_mb"], body["effective"]["memory_mb"]) == (512, 300)
    assert (body["requested"]["requests_per_minute"], body["effective"]["requests_per_minute"]) == (60, 60)


def test_effective_is_the_lowest_of_requested_maximum_and_override(weather, maximums, superadmin_client):
    maximums.PLUGINS_MAX_DB_CONNECTIONS = "3"

    body = _patch(superadmin_client, memory_mb=128, requests_per_minute=60, cpu_priority="low").json()

    assert body["overrides"] == {"memory_mb": 128, "requests_per_minute": 60, "cpu_priority": "low"}
    assert body["effective"] == {"memory_mb": 128, "db_connections": 3, "statement_timeout_seconds": 10, "requests_per_minute": 60, "cpu_priority": "low"}


def test_the_desired_state_follows_the_effective_memory_and_priority(weather, superadmin_client, node_client):
    before = _desired_runtime(node_client)

    _patch(superadmin_client, memory_mb=96, cpu_priority="low")

    assert (before["memory_mb"], before["cpu_priority"]) == (256, "normal")
    assert (_desired_runtime(node_client)["memory_mb"], _desired_runtime(node_client)["cpu_priority"]) == (96, "low")


def test_null_removes_an_override(weather, superadmin_client):
    _patch(superadmin_client, memory_mb=128, cpu_priority="low")

    body = _patch(superadmin_client, memory_mb=None).json()

    assert body["overrides"] == {"cpu_priority": "low"}
    assert body["effective"]["memory_mb"] == 256
    assert Plugin.objects.get(identifier="weather").limit_overrides == {"cpu_priority": "low"}


@pytest.mark.parametrize(
    ("overrides", "loc"),
    [
        ({"disk_mb": 10}, "overrides.disk_mb"),
        ({"memory_mb": 0}, "overrides.memory_mb"),
        ({"memory_mb": -1}, "overrides.memory_mb"),
        ({"memory_mb": "128"}, "overrides.memory_mb"),
        ({"memory_mb": 1.5}, "overrides.memory_mb"),
        ({"memory_mb": True}, "overrides.memory_mb"),
        ({"memory_mb": 257}, "overrides.memory_mb"),
        ({"statement_timeout_seconds": 11}, "overrides.statement_timeout_seconds"),
        ({"cpu_priority": "normal"}, "overrides.cpu_priority"),
        ({"cpu_priority": "high"}, "overrides.cpu_priority"),
    ],
)
def test_an_override_can_only_lower_a_limit(weather, superadmin_client, overrides, loc):
    response = superadmin_client.patch(LIMITS_URL, {"overrides": overrides}, format="json")

    assert response.status_code == 400
    assert response.json()["code"] == "invalid_plugin_limits"
    assert [error["loc"] for error in response.json()["errors"]] == [loc]
    assert Plugin.objects.get(identifier="weather").limit_overrides == {}


def test_an_override_is_bounded_by_a_lowered_platform_maximum(weather, maximums, superadmin_client):
    maximums.PLUGINS_MAX_PROCESS_MEMORY_MB = "200"

    assert _patch(superadmin_client, memory_mb=201).status_code == 400
    assert _patch(superadmin_client, memory_mb=200).status_code == 200


def test_writes_are_logged(weather, superadmin_client, mocker):
    info = mocker.patch("plugins.audit.logger.info")

    _patch(superadmin_client, memory_mb=128)

    info.assert_called_once()
    assert info.call_args.kwargs["overrides"] == "memory_mb=128"


def test_a_plugin_without_a_backend_has_no_limits(running_plugin, superadmin_client):
    running_plugin()

    assert superadmin_client.get(LIMITS_URL).json()["code"] == "plugin_has_no_backend"


def test_an_org_admin_is_refused(weather, client_as, admin_acme):
    assert _patch(client_as(admin_acme), memory_mb=128).status_code == 403
