"""What a node reports about a plugin's database: the record it updates and the activity it writes."""

from datetime import datetime, timedelta
from datetime import timezone as dt_timezone

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from plugins.models import (
    ActivityAction,
    Plugin,
    PluginActivityEvent,
    PluginDatabase,
    PluginDatabaseState,
    PluginPlacement,
    PluginState,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("plugins_enabled", "package_store", "spa_root")]

REPORTS_URL = "/api/plugin-nodes/self/reports/"
START = datetime(2026, 10, 21, 12, 0, tzinfo=dt_timezone.utc)
DATABASE_ACTIONS = (
    ActivityAction.DATABASE_READY,
    ActivityAction.DATABASE_FAILED,
    ActivityAction.DATABASE_LIMIT_RESTORED,
)


@pytest.fixture
def clock(monkeypatch):
    """`timezone.now()` under the test's control; starts at `START`."""
    now = {"value": START}
    monkeypatch.setattr(timezone, "now", lambda: now["value"])

    def advance(**delta):
        now["value"] += timedelta(**delta)
        return now["value"]

    advance.now = lambda: now["value"]
    return advance


@pytest.fixture
def weather(database_plugin):
    return database_plugin()


def _record():
    return PluginDatabase.objects.get()


def _database(state, **changes):
    return {
        "installation_id": _record().installation_id,
        "state": state,
        "applied_migrations": [],
        **changes,
    }


def _send(node_client, plugin, database, **observed):
    placement = PluginPlacement.objects.get(plugin=plugin)
    entry = {
        "placement_id": placement.pk,
        "observed_state": "starting",
        "health": "unknown",
        "restarts": 0,
        "applied_settings_revision": 0,
        "applied_restart_generation": 0,
        "database": database,
        **observed,
    }
    response = node_client.post(
        REPORTS_URL,
        {"format": 1, "agent_version": "0.1.0", "reported_at": "2026-10-21T12:00:05Z", "placements": [entry]},
        format="json",
    )
    assert response.status_code == 204, response.content


def _events():
    return list(
        PluginActivityEvent.objects.filter(action__in=DATABASE_ACTIONS)
        .order_by("pk")
        .values_list("action", "detail")
    )


def _ready(node_client, weather, migrations=("001_places.sql",), **changes):
    _send(node_client, weather, _database("ready", applied_migrations=list(migrations), **changes))


# ---- each report state ----


@pytest.mark.parametrize("before", [PluginDatabaseState.PENDING, PluginDatabaseState.READY, PluginDatabaseState.FAILED])
def test_provisioning_is_stored_from_any_state_without_an_event(weather, node_client, clock, before):
    PluginDatabase.objects.update(state=before)

    _send(node_client, weather, _database("provisioning", last_error="plugins_db is not reachable"))

    record = _record()
    assert (record.state, record.last_error) == (PluginDatabaseState.PROVISIONING, "plugins_db is not reachable")
    assert _events() == []


def test_the_first_ready_stores_the_ledger_and_the_size_and_is_recorded(weather, node_client, clock):
    PluginDatabase.objects.update(last_error="plugins_db is not reachable")

    _ready(node_client, weather, ("001_places.sql", "002_runs.sql"), size_bytes=8_421_376)

    record = _record()
    assert record.state == PluginDatabaseState.READY
    assert record.applied_migrations == ["001_places.sql", "002_runs.sql"]
    assert (record.size_bytes, record.last_error, record.ready_at) == (8_421_376, None, START)
    assert _events() == [(ActivityAction.DATABASE_READY, {"migrations_applied": 2})]


def test_ready_again_with_the_same_ledger_after_an_agent_restart_adds_no_event(weather, node_client, clock):
    _ready(node_client, weather)
    clock(minutes=5)

    _send(node_client, weather, _database("provisioning"))
    _ready(node_client, weather, size_bytes=9000)

    record = _record()
    assert (record.ready_at, record.size_bytes) == (START, 9000)
    assert [action for action, _ in _events()] == [ActivityAction.DATABASE_READY]


def test_ready_with_a_new_migration_is_recorded_again(weather, node_client, clock):
    _ready(node_client, weather)

    _ready(node_client, weather, ("001_places.sql", "002_runs.sql"))

    assert _events() == [
        (ActivityAction.DATABASE_READY, {"migrations_applied": 1}),
        (ActivityAction.DATABASE_READY, {"migrations_applied": 2}),
    ]
    assert _record().ready_at == START


def test_a_failure_is_recorded_once_on_the_change_into_failed(weather, node_client, clock):
    error = "plugins_db already has roles that this plugin installation did not create"

    _send(node_client, weather, _database("failed", last_error=error))
    _send(node_client, weather, _database("failed", last_error=error))

    record = _record()
    assert (record.state, record.last_error) == (PluginDatabaseState.FAILED, error)
    assert _events() == [(ActivityAction.DATABASE_FAILED, {"error": error})]


def test_ready_after_a_failure_clears_the_error_and_is_recorded(weather, node_client, clock):
    _ready(node_client, weather)
    failed_at = clock(minutes=1)
    _send(node_client, weather, _database("failed", last_error="001_places.sql line 1: [42601] syntax error"))
    assert _record().failed_at == failed_at
    # The node provisions again before it reports the database ready.
    _send(node_client, weather, _database("provisioning"))
    assert _record().failed_at == failed_at

    _ready(node_client, weather)

    assert (_record().state, _record().last_error, _record().failed_at) == (PluginDatabaseState.READY, None, None)
    assert [action for action, _ in _events()] == [
        ActivityAction.DATABASE_READY,
        ActivityAction.DATABASE_FAILED,
        ActivityAction.DATABASE_READY,
    ]


def test_a_failure_reported_again_after_provisioning_is_recorded_once(weather, node_client, clock):
    error = "001_places.sql line 1: [42601] syntax error"
    _send(node_client, weather, _database("failed", last_error=error))
    _send(node_client, weather, _database("provisioning"))
    _send(node_client, weather, _database("failed", last_error=error))

    assert [action for action, _ in _events()] == [ActivityAction.DATABASE_FAILED]
    assert _record().failed_at == START


def test_ready_again_without_a_failure_in_between_is_not_recorded_again(weather, node_client, clock):
    _ready(node_client, weather)
    _send(node_client, weather, _database("provisioning"))

    _ready(node_client, weather)

    assert [action for action, _ in _events()] == [ActivityAction.DATABASE_READY]


def test_events_are_deployment_wide_and_the_platform_s(weather, node_client, clock):
    _ready(node_client, weather)

    event = PluginActivityEvent.objects.get(action=ActivityAction.DATABASE_READY)
    assert (event.plugin_identifier, event.organization_id) == ("weather", None)
    assert (event.actor_kind, event.actor_label, event.actor_user_id) == ("platform", "Platform", None)


# ---- the restored timeout ----


def test_a_restore_is_stored_and_recorded(weather, node_client, clock):
    restored_at = clock(minutes=1)

    _ready(node_client, weather, limits_restored_at=restored_at.isoformat())

    record = _record()
    assert (record.limits_restored_at, record.limits_restored_event_at) == (restored_at, restored_at)
    assert _events()[-1] == (ActivityAction.DATABASE_LIMIT_RESTORED, {"setting": "statement_timeout"})


def test_restores_are_recorded_at_most_once_an_hour(weather, node_client, clock):
    first = clock(minutes=1)
    _ready(node_client, weather, limits_restored_at=first.isoformat())
    second = clock(minutes=30)
    _ready(node_client, weather, limits_restored_at=second.isoformat())
    third = clock(minutes=31)
    _ready(node_client, weather, limits_restored_at=third.isoformat())

    record = _record()
    assert record.limits_restored_at == third
    restored = [action for action, _ in _events() if action == ActivityAction.DATABASE_LIMIT_RESTORED]
    assert len(restored) == 2


def test_a_restore_already_stored_is_not_recorded_again(weather, node_client, clock):
    restored_at = clock(minutes=1)
    _ready(node_client, weather, limits_restored_at=restored_at.isoformat())
    clock(hours=2)

    _ready(node_client, weather, limits_restored_at=restored_at.isoformat())

    assert [action for action, _ in _events()].count(ActivityAction.DATABASE_LIMIT_RESTORED) == 1


# ---- what is ignored ----


def test_a_report_about_another_installation_is_ignored(weather, node_client, clock):
    database = _database("failed", last_error="leftover")
    database["installation_id"] = "f" * 32

    _send(node_client, weather, database)

    assert (_record().state, _record().last_error) == (PluginDatabaseState.PENDING, None)
    assert _events() == []


def test_a_report_without_a_database_section_leaves_the_record(weather, node_client, clock):
    _ready(node_client, weather)

    _send(node_client, weather, None)

    assert _record().state == PluginDatabaseState.READY


def test_a_database_section_for_a_plugin_without_a_database_is_ignored(backend_plugin, plugin_node, node_client, clock):
    plugin = backend_plugin()
    placement = PluginPlacement.objects.get(plugin=plugin)
    response = node_client.post(
        REPORTS_URL,
        {
            "format": 1,
            "agent_version": "0.1.0",
            "reported_at": "2026-10-21T12:00:05Z",
            "placements": [
                {
                    "placement_id": placement.pk,
                    "observed_state": "starting",
                    "health": "unknown",
                    "restarts": 0,
                    "database": {"installation_id": "a" * 32, "state": "ready", "applied_migrations": []},
                }
            ],
        },
        format="json",
    )

    assert response.status_code == 204
    assert not PluginDatabase.objects.exists()
    assert _events() == []


# ---- the plugin's state ----


def test_a_failed_database_fails_the_plugin_through_its_placement(weather, node_client, clock):
    error = "001_places.sql line 1: [42601] syntax error"

    _send(
        node_client, weather, _database("failed", last_error=error), observed_state="failed", last_error=error
    )

    assert Plugin.objects.get(pk=weather.pk).state == PluginState.FAILED
    assert PluginPlacement.objects.get(plugin=weather).last_error == error


def test_the_database_sections_of_a_report_cost_one_query_however_many_there_are(database_plugin, node_client, clock):
    plugins = [database_plugin(), database_plugin(id="forecast"), database_plugin(id="tides")]

    def queries_of(reported, *, with_database):
        entries = []
        for plugin in reported:
            database = None
            if with_database:
                record = PluginDatabase.objects.get(plugin=plugin)
                database = {"installation_id": record.installation_id, "state": "provisioning", "applied_migrations": []}
            entries.append(
                {
                    "placement_id": PluginPlacement.objects.get(plugin=plugin).pk,
                    "observed_state": "starting",
                    "health": "unknown",
                    "restarts": 0,
                    "database": database,
                }
            )
        body = {"format": 1, "agent_version": "0.1.0", "reported_at": "2026-10-21T12:00:05Z", "placements": entries}
        with CaptureQueriesContext(connection) as captured:
            assert node_client.post(REPORTS_URL, body, format="json").status_code == 204
        return len(captured.captured_queries)

    # The first report moves every record to provisioning; the ones measured change nothing.
    queries_of(plugins, with_database=True)

    for reported in (plugins[:1], plugins):
        extra = queries_of(reported, with_database=True) - queries_of(reported, with_database=False)
        assert extra == 1
