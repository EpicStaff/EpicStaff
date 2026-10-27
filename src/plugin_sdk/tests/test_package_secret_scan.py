"""The package secret scan: no packaged file may hold a service-account key or a runtime file."""

import json
import os

import pytest

from epicstaff_plugin.package_layout import (
    SECRET_PROBLEM,
    SECRET_SCAN_BYTES,
    read_package_file,
    secret_problem,
)
from epicstaff_plugin.package_source import collect_source
from epicstaff_plugin.problems import PackageProblemsError
from epicstaff_plugin.testing import service_account_key, write_runtime_file
from package_helpers import sample_files, write_archive


def _refused(path, data, *, complete=True):
    problem = secret_problem(path, data, complete=complete)
    return problem is not None and (problem.loc, problem.message) == (f"package.{path}", SECRET_PROBLEM)


@pytest.mark.parametrize(
    "text",
    [
        "{key}",
        'API_KEY = "{key}"\n',
        "Authorization: PluginKey {key}\r\n",
        "KEY={key};",
        "{{\"key\":\"{key}\"}}",
    ],
    ids=["alone", "python string", "header", "assignment", "json value"],
)
def test_a_service_account_key_anywhere_in_a_file_is_refused(text):
    assert _refused("backend/src/weather_plugin/settings.py", text.format(key=service_account_key()).encode())


@pytest.mark.parametrize(
    "text",
    [
        "esp-" + "a" * 42,
        "esp-" + "a" * 44,
        "desp-" + "a" * 43,
        "esp-" + "a" * 43 + "_tail",
        "esp_" + "a" * 43,
    ],
    ids=["too short", "too long", "inside a longer word", "inside a longer token", "another prefix"],
)
def test_text_that_only_resembles_a_key_is_not_refused(text):
    assert secret_problem("spa/app.js", text.encode(), complete=True) is None


def test_a_runtime_file_the_node_would_write_is_refused(tmp_path, signer):
    runtime_file = tmp_path / "runtime.json"
    write_runtime_file(runtime_file, signer=signer)

    assert _refused("backend/src/runtime.json", runtime_file.read_bytes())


def test_a_runtime_file_document_is_refused_by_its_fields_even_without_a_key():
    document = {"secret_settings": {"forecast_api_token": "t"}, "service_accounts": {}, "format": 1}

    assert _refused("spa/config.json", json.dumps(document, indent=2).encode())
    assert _refused("spa/config.json", b"\xef\xbb\xbf \n" + json.dumps(document).encode())


@pytest.mark.parametrize(
    "data",
    [
        json.dumps({"service_accounts": {}}).encode(),
        json.dumps({"secret_settings": {}}).encode(),
        json.dumps([{"service_accounts": {}, "secret_settings": {}}]).encode(),
        b'{"service_accounts": {}, "secret_settings": {}',
        b'{"a":' * 100_000 + b"1" + b"}" * 100_000,
        b"\xff\xfe{",
    ],
    ids=["one field", "the other field", "not an object", "not json", "nested past the parser", "not utf-8"],
)
def test_other_json_is_not_refused(data):
    assert secret_problem("spa/config.json", data, complete=True) is None


def test_a_document_larger_than_the_scanned_head_is_not_parsed():
    document = json.dumps({"service_accounts": {}, "secret_settings": {}}).encode()

    assert secret_problem("spa/config.json", document, complete=False) is None


def test_a_wheel_is_never_scanned():
    assert secret_problem("backend/wheels/demo-1.0-py3-none-any.whl", service_account_key().encode(), complete=True) is None


def test_the_archive_reader_refuses_a_file_with_a_key_and_names_only_the_file(tmp_path):
    key = service_account_key()
    files = {**sample_files(), "spa/config.js": f'export const key = "{key}";\n'.encode()}
    package = write_archive(tmp_path / "weather.esplugin", files)

    with pytest.raises(PackageProblemsError) as raised:
        read_package_file(package)

    assert [(problem.loc, problem.message) for problem in raised.value.problems] == [
        ("package.spa/config.js", SECRET_PROBLEM)
    ]
    assert key not in str(raised.value)


def test_the_archive_reader_scans_only_the_head_of_a_large_file(tmp_path):
    # Random padding does not compress, so neither file trips the compression-ratio check, which
    # would refuse it unread. The newlines keep each key a token of its own.
    late_key = os.urandom(SECRET_SCAN_BYTES - 11) + b"\n" + service_account_key().encode()
    early_key = service_account_key().encode() + b"\n" + os.urandom(SECRET_SCAN_BYTES)
    files = {**sample_files(), "spa/late.txt": late_key, "spa/early.txt": early_key}
    package = write_archive(tmp_path / "weather.esplugin", files)

    with pytest.raises(PackageProblemsError) as raised:
        read_package_file(package)

    assert [problem.loc for problem in raised.value.problems if problem.message == SECRET_PROBLEM] == [
        "package.spa/early.txt"
    ]


def test_the_archive_reader_does_not_scan_wheels(tmp_path):
    files = {**sample_files(), "backend/wheels/demo-1.0-py3-none-any.whl": service_account_key().encode()}
    package = write_archive(tmp_path / "weather.esplugin", files)

    with pytest.raises(PackageProblemsError) as raised:
        read_package_file(package)

    # Refused for its place in a frontend-only package, never for its content.
    assert [problem.message for problem in raised.value.problems if problem.message == SECRET_PROBLEM] == []


def test_the_source_scan_reads_the_files_pack_would_take(weather_source, signer):
    write_runtime_file(weather_source / "backend" / "src" / "weather-development-runtime.json", signer=signer)
    (weather_source / "database" / "migrations" / "004_notes.sql").write_text(f"-- {service_account_key()}\n")
    # Outside backend/ and database/: never packed, so never scanned.
    write_runtime_file(weather_source / "weather-development-runtime.json", signer=signer)

    problems = collect_source(weather_source, None).secret_problems()

    assert [(problem.loc, problem.message) for problem in problems] == [
        ("package.backend/src/weather-development-runtime.json", SECRET_PROBLEM),
        ("package.database/migrations/004_notes.sql", SECRET_PROBLEM),
    ]


def test_the_weather_sample_holds_no_secret(weather_source):
    assert collect_source(weather_source, None).secret_problems() == []
