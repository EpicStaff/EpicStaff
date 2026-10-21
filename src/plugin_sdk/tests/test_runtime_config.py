import json
import logging

import pytest
from pydantic import ValidationError

from epicstaff_plugin.contracts.runtime import RuntimeFile
from epicstaff_plugin.runtime import RuntimeConfig, RuntimeConfigError, runtime_config
from epicstaff_plugin.testing import write_runtime_file

PUBLIC_PING = {"path": "/api/ping", "match": "exact", "methods": ["GET"], "rate_limit_per_minute": 60, "max_body_kb": 0}


def test_every_field_of_the_runtime_file_is_readable(tmp_path, signer):
    path = tmp_path / "runtime.json"
    write_runtime_file(
        path,
        signer=signer,
        settings={"units": "imperial", "days": 3, "alerts": True},
        secret_settings={"forecast_api_token": "s3cret-token"},
        public_paths=[PUBLIC_PING],
    )

    config = RuntimeConfig.load(path)

    assert (config.plugin_identifier, config.plugin_version) == ("weather", "0.2.0")
    assert config.issuer == config.epicstaff_public_url == "https://epicstaff.example.com"
    assert config.public_url == "https://weather.plugins.epicstaff.test"
    assert config.epicstaff_api_url == "http://epicstaff-api:8081/api/"
    assert dict(config.settings) == {"units": "imperial", "days": 3, "alerts": True}
    assert config.setting("days") == 3
    assert config.setting("missing", "fallback") == "fallback"
    assert config.secret_setting("forecast_api_token") == "s3cret-token"
    assert config.secret_setting("missing") is None
    assert dict(config.service_accounts) == {}
    assert config.jwks == signer.jwks
    assert [public_path.path for public_path in config.public_paths] == ["/api/ping"]


def test_the_settings_cannot_be_changed_through_the_accessor(runtime):
    with pytest.raises(TypeError):
        runtime.settings["units"] = "imperial"


def test_a_rewritten_file_is_read_again(runtime_file, signer):
    config = RuntimeConfig.load(runtime_file)
    first = config.document

    write_runtime_file(runtime_file, signer=signer, settings={"units": "imperial"})

    assert config.setting("units") == "imperial"
    assert config.document is not first


def test_an_unchanged_file_is_not_read_again(runtime):
    assert runtime.document is runtime.document


def test_a_bad_rewrite_keeps_the_previous_content(runtime_file, caplog):
    config = RuntimeConfig.load(runtime_file)
    runtime_file.write_text('{"format": 1}')

    with caplog.at_level(logging.WARNING):
        assert config.setting("units") == "metric"
    assert "Keeping the previous runtime file" in caplog.text


def test_a_missing_file_later_keeps_the_previous_content(runtime_file):
    config = RuntimeConfig.load(runtime_file)
    runtime_file.unlink()

    assert config.setting("units") == "metric"


def test_fields_a_newer_epicstaff_adds_are_ignored(runtime_file):
    document = json.loads(runtime_file.read_text())
    document["egress_proxy"] = {"url": "http://proxy:3128"}
    document["jwks"]["keys"][0]["x5c"] = []
    runtime_file.write_text(json.dumps(document))

    assert RuntimeConfig.load(runtime_file).plugin_identifier == "weather"


def test_epicstaff_cannot_build_a_runtime_file_with_an_unknown_field(runtime_file):
    document = json.loads(runtime_file.read_text())
    document["egress_proxy"] = {}

    with pytest.raises(ValidationError):
        RuntimeFile.model_validate(document)


@pytest.mark.parametrize(
    "overrides",
    [
        {"issuer": "ftp://epicstaff.example.com"},
        {"epicstaff_api_url": "http://user:password@epicstaff-api/api/"},
        {"settings": {"Units": "metric"}},
        {"settings": {"units": 1.5}},
        {"jwks": {"keys": []}},
    ],
)
def test_a_runtime_file_that_breaks_the_contract_cannot_be_written(tmp_path, overrides):
    with pytest.raises(ValidationError):
        write_runtime_file(tmp_path / "runtime.json", **overrides)


def test_an_invalid_file_is_refused_without_repeating_its_secrets(tmp_path, signer):
    path = tmp_path / "runtime.json"
    write_runtime_file(path, signer=signer, secret_settings={"forecast_api_token": "s3cret-token"})
    document = json.loads(path.read_text())
    document["secret_settings"]["forecast_api_token"] = ["s3cret-token"]
    path.write_text(json.dumps(document))

    with pytest.raises(RuntimeConfigError) as raised:
        RuntimeConfig.load(path)

    assert "runtime.secret_settings.forecast_api_token" in str(raised.value)
    assert "s3cret-token" not in str(raised.value)


def test_a_missing_file_is_refused(tmp_path):
    with pytest.raises(RuntimeConfigError, match="cannot read"):
        RuntimeConfig.load(tmp_path / "absent.json")


def test_load_reads_the_file_the_environment_names(monkeypatch, runtime_file):
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))

    assert RuntimeConfig.load().path == runtime_file


def test_load_without_the_variable_is_refused(monkeypatch):
    monkeypatch.delenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", raising=False)

    with pytest.raises(RuntimeConfigError, match="EPICSTAFF_PLUGIN_RUNTIME_FILE is not set"):
        RuntimeConfig.load()


def test_the_process_shares_one_configuration_per_runtime_file(monkeypatch, runtime_file, tmp_path):
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(runtime_file))
    first = runtime_config()

    assert runtime_config() is first

    other = tmp_path / "other.json"
    write_runtime_file(other)
    monkeypatch.setenv("EPICSTAFF_PLUGIN_RUNTIME_FILE", str(other))
    assert runtime_config() is not first


@pytest.mark.parametrize(
    "secret_settings",
    [{"forecast_api_token": ["s3cret-token"]}, {"Bad Key": "s3cret-token"}, {"forecast_api_token": 12345678}],
)
def test_a_validation_error_never_repeats_a_secret(runtime_file, secret_settings):
    document = json.loads(runtime_file.read_text())
    document["secret_settings"] = secret_settings

    with pytest.raises(ValidationError) as from_python:
        RuntimeFile.model_validate(document)
    with pytest.raises(ValidationError) as from_json:
        RuntimeFile.model_validate_json(json.dumps(document))

    for error in (from_python.value, from_json.value):
        assert "secret_settings" in str(error)
        assert "s3cret-token" not in str(error)
        assert "12345678" not in str(error)
