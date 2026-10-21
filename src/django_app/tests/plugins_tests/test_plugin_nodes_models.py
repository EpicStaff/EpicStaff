"""The documents django_app and a plugin node exchange about a plugin's database and outbound hosts."""

import json

import pytest
from epicstaff_plugin.contracts.manifest import MAX_OUTBOUND_HOSTS
from pydantic import ValidationError

from src.shared.models.plugin_nodes import (
    MAX_APPLIED_MIGRATIONS,
    DatabaseNames,
    DesiredPlacement,
    DesiredState,
    NodeReport,
    RuntimeCredentials,
    RuntimeDatabaseCredentials,
    database_names_for,
)

APP_PASSWORD = "Xk3_-9qZtR7vLm2NpQs8WcYe4HjBfAu6DgKoIn1E5rT"
INSTALLATION_ID = "0f8c2d4e6a1b3c5d7e9f0a2b4c6d8e0f"
NAME_FIELDS = ("database_name", "owner_role", "app_role", "job_role")


def _database(identifier="weather", **changes):
    names = database_names_for(identifier)
    return {
        "server": {"name": "plugins_db", "host": "plugins_db", "port": 5432},
        "installation_id": INSTALLATION_ID,
        "database_name": names.database,
        "owner_role": names.owner_role,
        "app_role": names.app_role,
        "job_role": names.job_role,
        "connection_limit": 3,
        "statement_timeout_seconds": 10,
        **changes,
    }


def _placement(identifier="weather", **changes):
    return {
        "placement_id": 1,
        "plugin_identifier": identifier,
        "desired_state": "running",
        "restart_generation": 0,
        "package": {
            "package_id": 1,
            "version": "0.5.0",
            "sha256": "a" * 64,
            "size": 1024,
            "trust": "untrusted",
            "signer_public_key": None,
        },
        "runtime": {
            "python": "3.12",
            "entrypoint": "plugin.app:app",
            "port": 20001,
            "unix_uid": 20000,
            "memory_mb": 256,
            "cpu_priority": "normal",
        },
        "credentials_revision": "b" * 64,
        "settings_revision": 0,
        **changes,
    }


def _desired_state(*placements):
    return {
        "format": 1,
        "node": {"name": "node-1"},
        "revision": "c" * 64,
        "generated_at": "2026-10-21T10:00:00Z",
        "placements": list(placements),
    }


def _credentials(**changes):
    return {
        "placement_id": 1,
        "credentials_revision": "b" * 64,
        "settings_revision": 0,
        "runtime_file": {
            "format": 1,
            "plugin": {"identifier": "weather", "version": "0.5.0"},
            "issuer": "https://epicstaff.example.com",
            "public_url": "https://weather.plugins.example.com",
            "epicstaff_public_url": "https://epicstaff.example.com",
            "epicstaff_api_url": "http://django_app:8000/api/",
            "settings": {},
            "secret_settings": {},
            "service_accounts": {},
            "jwks": {
                "keys": [
                    {
                        "kty": "OKP",
                        "crv": "Ed25519",
                        "x": "1" * 43,
                        "kid": "0123456789abcdef",
                        "alg": "EdDSA",
                        "use": "sig",
                    }
                ]
            },
            "public_paths": [],
        },
        **changes,
    }


def _placement_report(**changes):
    return {
        "placement_id": 1,
        "observed_state": "running",
        "health": "ok",
        "restarts": 0,
        **changes,
    }


def _node_report(*placements):
    return {
        "format": 1,
        "agent_version": "1.0.0",
        "reported_at": "2026-10-21T10:00:00Z",
        "placements": list(placements),
    }


def _database_report(**changes):
    return {
        "installation_id": INSTALLATION_ID,
        "state": "ready",
        "applied_migrations": ["001_places.sql"],
        **changes,
    }


def test_a_dash_in_the_identifier_becomes_an_underscore_in_every_name():
    assert database_names_for("my-plugin") == DatabaseNames(
        database="plugin_my_plugin",
        owner_role="my_plugin_owner",
        app_role="my_plugin_app",
        job_role="my_plugin_job",
    )


def test_a_plugin_named_like_a_template_database_gets_a_database_of_its_own():
    assert database_names_for("template1") == DatabaseNames(
        database="plugin_template1",
        owner_role="template1_owner",
        app_role="template1_app",
        job_role="template1_job",
    )


def test_the_longest_identifier_gives_names_of_at_most_39_characters():
    longest = "a" + "b" * 30 + "c"

    names = database_names_for(longest)

    assert len(longest) == 32
    assert len(names.database) == 39
    assert max(len(name) for name in (names.owner_role, names.app_role, names.job_role)) <= 39


IDENTIFIERS_THAT_LOOK_ALIKE = (
    "ab",
    "a-b",
    "a-b-c",
    "ab-c",
    "a-bc",
    "app",
    "owner",
    "job",
    "x-app",
    "x-owner",
    "x-job",
    "x-app-app",
    "x-app-job",
    "plugin-x",
    "template1",
)


def test_no_two_plugins_share_a_database_name():
    databases = [database_names_for(identifier).database for identifier in IDENTIFIERS_THAT_LOOK_ALIKE]

    assert len(set(databases)) == len(databases)
    assert not {"postgres", "template0", "template1"} & set(databases)


def test_no_two_plugins_share_a_role_name_and_none_takes_a_platform_role():
    roles = [
        role
        for identifier in IDENTIFIERS_THAT_LOOK_ALIKE
        for role in (
            database_names_for(identifier).owner_role,
            database_names_for(identifier).app_role,
            database_names_for(identifier).job_role,
        )
    ]

    assert len(set(roles)) == len(roles)
    assert not {"postgres", "plugins_admin", "plugins_backup"} & set(roles)


def test_a_placement_with_its_own_database_names_is_accepted():
    placement = DesiredPlacement.model_validate(_placement(database=_database()))

    assert placement.database.database_name == "plugin_weather"
    assert placement.database.owner_role == "weather_owner"
    assert placement.database.app_role == "weather_app"
    assert placement.database.job_role == "weather_job"
    assert placement.database.server.host == "plugins_db"


@pytest.mark.parametrize("field", NAME_FIELDS)
def test_a_placement_pointed_at_another_plugins_database_or_role_is_refused(field):
    other = database_names_for("forecast")
    other_name = {
        "database_name": other.database,
        "owner_role": other.owner_role,
        "app_role": other.app_role,
        "job_role": other.job_role,
    }[field]

    with pytest.raises(ValidationError) as raised:
        DesiredPlacement.model_validate(_placement(database=_database(**{field: other_name})))

    assert "database names must be the ones derived from plugin_identifier" in str(raised.value)


def test_a_placement_whose_database_belongs_to_another_plugin_entirely_is_refused():
    with pytest.raises(ValidationError):
        DesiredPlacement.model_validate(_placement("weather", database=_database("forecast")))


def test_a_placement_for_the_other_plugin_accepts_its_names():
    placement = DesiredPlacement.model_validate(_placement("forecast", database=_database("forecast")))

    assert placement.database.app_role == "forecast_app"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("connection_limit", 0),
        ("connection_limit", 101),
        ("statement_timeout_seconds", 0),
        ("statement_timeout_seconds", 601),
    ],
)
def test_a_database_limit_outside_the_manifest_bounds_is_refused(field, value):
    with pytest.raises(ValidationError):
        DesiredPlacement.model_validate(_placement(database=_database(**{field: value})))


def test_a_placement_without_a_database_or_egress_has_none_and_no_hosts():
    placement = DesiredPlacement.model_validate(_placement())

    assert placement.database is None
    assert placement.egress.hosts == []


def test_egress_keeps_the_hosts_in_manifest_order():
    hosts = ["geocoding-api.open-meteo.com", "*.example.org", "api.example.com"]

    placement = DesiredPlacement.model_validate(_placement(egress={"hosts": hosts}))

    assert placement.egress.hosts == hosts


@pytest.mark.parametrize("host", ["10.0.0.1", "api.example.com:443", "API.example.com", "localhost"])
def test_egress_refuses_a_host_the_manifest_would_refuse(host):
    with pytest.raises(ValidationError):
        DesiredPlacement.model_validate(_placement(egress={"hosts": [host]}))


def test_egress_holds_at_most_the_manifests_number_of_hosts():
    hosts = [f"host{index}.example.com" for index in range(MAX_OUTBOUND_HOSTS + 1)]

    DesiredPlacement.model_validate(_placement(egress={"hosts": hosts[:MAX_OUTBOUND_HOSTS]}))
    with pytest.raises(ValidationError):
        DesiredPlacement.model_validate(_placement(egress={"hosts": hosts}))


def test_a_desired_state_from_an_older_server_reads_without_the_new_sections():
    body = json.dumps(_desired_state(_placement()))

    state = DesiredState.model_validate_json(body, extra="ignore")

    [placement] = state.placements
    assert placement.database is None
    assert placement.egress.hosts == []


def test_a_newer_server_adding_fields_inside_the_new_sections_is_read_leniently():
    database = _database(future_field=1, server={"name": "plugins_db", "host": "plugins_db", "port": 5432, "tls": True})
    body = json.dumps(_desired_state(_placement(database=database, egress={"hosts": ["api.example.com"], "mode": "x"})))

    state = DesiredState.model_validate_json(body, extra="ignore")

    [placement] = state.placements
    assert placement.database.app_role == "weather_app"
    assert placement.database.server.port == 5432
    assert placement.egress.hosts == ["api.example.com"]
    with pytest.raises(ValidationError) as raised:
        DesiredState.model_validate_json(body)
    assert {error["type"] for error in raised.value.errors()} == {"extra_forbidden"}


def test_the_name_rule_still_applies_when_the_desired_state_is_read_leniently():
    body = json.dumps(_desired_state(_placement(database=_database(app_role="forecast_app"))))

    with pytest.raises(ValidationError):
        DesiredState.model_validate_json(body, extra="ignore")


def test_runtime_credentials_carry_the_app_password_only_when_given_one():
    without = RuntimeCredentials.model_validate(_credentials())
    with_database = RuntimeCredentials.model_validate(_credentials(database={"app_password": APP_PASSWORD}))

    assert without.database is None
    assert with_database.database.app_password == APP_PASSWORD
    assert with_database.model_dump(mode="json")["database"] == {"app_password": APP_PASSWORD}


def test_newer_runtime_credentials_are_read_leniently():
    body = json.dumps(_credentials(database={"app_password": APP_PASSWORD, "rotated_at": None}))

    credentials = RuntimeCredentials.model_validate_json(body, extra="ignore")

    assert credentials.database.app_password == APP_PASSWORD


def test_the_app_password_never_shows_in_a_repr():
    credentials = RuntimeCredentials.model_validate(_credentials(database={"app_password": APP_PASSWORD}))

    assert APP_PASSWORD not in repr(credentials)
    assert APP_PASSWORD not in str(credentials)
    assert APP_PASSWORD not in repr(credentials.database)


@pytest.mark.parametrize(
    "password",
    [
        APP_PASSWORD[:-1],
        APP_PASSWORD + "A",
        APP_PASSWORD[:-1] + "+",
        APP_PASSWORD[:-1] + "/",
        APP_PASSWORD[:-1] + "=",
    ],
)
def test_a_malformed_app_password_is_refused_without_showing_it(password):
    with pytest.raises(ValidationError) as raised:
        RuntimeCredentials.model_validate(_credentials(database={"app_password": password}))

    assert password not in str(raised.value)
    assert password not in repr(raised.value)
    # What the node and django_app put in a log line or an error response from a failed parse.
    assert password not in json.dumps(raised.value.errors(include_input=False, include_url=False))


def test_the_app_password_never_shows_when_its_model_is_validated_alone():
    with pytest.raises(ValidationError) as raised:
        RuntimeDatabaseCredentials.model_validate({"app_password": APP_PASSWORD, "unexpected": APP_PASSWORD})

    assert APP_PASSWORD not in str(raised.value)
    assert APP_PASSWORD not in repr(raised.value)


def test_a_placement_report_carries_the_database_ledger():
    report = NodeReport.model_validate(
        _node_report(
            _placement_report(
                database=_database_report(
                    applied_migrations=["001_places.sql", "002_forecast_runs.sql"],
                    size_bytes=8_421_376,
                    limits_restored_at="2026-10-21T09:59:00Z",
                )
            )
        )
    )

    [placement] = report.placements
    assert placement.database.state == "ready"
    assert placement.database.applied_migrations == ["001_places.sql", "002_forecast_runs.sql"]
    assert placement.database.size_bytes == 8_421_376
    assert placement.database.limits_restored_at.isoformat() == "2026-10-21T09:59:00+00:00"


def test_a_report_from_an_older_node_has_no_database():
    report = NodeReport.model_validate_json(json.dumps(_node_report(_placement_report())), extra="ignore")

    assert report.placements[0].database is None


def test_a_report_from_a_newer_node_is_read_leniently():
    body = json.dumps(_node_report(_placement_report(database=_database_report(state="failed", last_error="conflict", pending=[])))
    )

    report = NodeReport.model_validate_json(body, extra="ignore")

    assert report.placements[0].database.last_error == "conflict"
    with pytest.raises(ValidationError):
        NodeReport.model_validate_json(body)


@pytest.mark.parametrize(
    "name",
    ["1_places.sql", "0001_places.sql", "001_Places.sql", "001_places.SQL", "001_.sql", "001-places.sql", "../001_places.sql", "001_places.sql.bak"],
)
def test_a_report_refuses_a_name_that_is_not_a_package_migration(name):
    with pytest.raises(ValidationError):
        NodeReport.model_validate(_node_report(_placement_report(database=_database_report(applied_migrations=[name]))))


def test_a_report_lists_at_most_one_migration_per_number():
    names = [f"{number:03d}_step.sql" for number in range(MAX_APPLIED_MIGRATIONS)]

    NodeReport.model_validate(_node_report(_placement_report(database=_database_report(applied_migrations=names))))
    with pytest.raises(ValidationError):
        NodeReport.model_validate(
            _node_report(_placement_report(database=_database_report(applied_migrations=[*names, "999_again.sql"])))
        )


def test_a_report_refuses_an_unknown_database_state():
    with pytest.raises(ValidationError):
        NodeReport.model_validate(_node_report(_placement_report(database=_database_report(state="pending"))))
