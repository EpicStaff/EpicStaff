"""`epicstaff-plugin dev`: its checks, the backend's environment, the uvicorn call and what it prints.

uvicorn.run is replaced by a recorder, which keeps the process environment and import path as
the backend would start with them. The Weather sample is the source, with a lock this test
environment satisfies.
"""

import importlib.metadata
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import uvicorn

from epicstaff_plugin.cli import development, development_database
from epicstaff_plugin.cli.main import main
from epicstaff_plugin import serve
from epicstaff_plugin.contracts import runtime as runtime_contract
from epicstaff_plugin.contracts.runtime import LISTEN_FD_ENVIRONMENT_VARIABLE, PORT_ENVIRONMENT_VARIABLE
from epicstaff_plugin.testing import ContextSigner, service_account_key, write_runtime_file
from fake_postgres import FakeConnection

ACME_KEY = service_account_key()
COBALT_KEY = service_account_key()
SECRET_SETTING = "forecast-token-that-must-never-show"
DATABASE_PASSWORD = "local-database-password"
DATABASE_URL = f"postgresql://weather_app:{DATABASE_PASSWORD}@localhost:5432/weather_development"
SECRETS = (ACME_KEY, COBALT_KEY, SECRET_SETTING, DATABASE_PASSWORD)
DEVELOPMENT_API_URL = "http://127.0.0.1:8082/api/"


def _lock_line(name, version):
    return f"{name}=={version} --hash=sha256:{'0' * 64}\n"


@pytest.fixture
def source(weather_source):
    """The Weather sample, its lock pinning only what this environment has installed."""
    (weather_source / "backend" / "requirements.lock").write_text(
        _lock_line("uvicorn", importlib.metadata.version("uvicorn"))
        + _lock_line("psycopg", importlib.metadata.version("psycopg"))
    )
    return weather_source


@pytest.fixture
def manifest(source):
    return json.loads((source / "manifest.json").read_text())


def _write_manifest(source, manifest):
    (source / "manifest.json").write_text(json.dumps(manifest))


@pytest.fixture
def runtime_file(tmp_path, manifest):
    """A development runtime file for Weather, downloaded outside the source, readable by its owner only."""
    path = tmp_path / "downloads" / "weather-development-runtime.json"
    path.parent.mkdir()
    signer = ContextSigner(plugin_identifier="weather", plugin_version=manifest["version"], issuer="http://epicstaff.localhost")
    write_runtime_file(
        path,
        signer=signer,
        epicstaff_api_url=DEVELOPMENT_API_URL,
        public_url="http://weather.plugins.epicstaff.localhost",
        secret_settings={"forecast_api_token": SECRET_SETTING},
        service_accounts={
            "7": {"key": COBALT_KEY, "org_name": "E2E Cobalt", "grant_state": "active"},
            "3": {"key": ACME_KEY, "org_name": "E2E Acme", "grant_state": "active"},
        },
        public_paths=manifest["public_paths"],
    )
    path.chmod(0o600)
    return path


@pytest.fixture
def process(monkeypatch):
    """Restores the environment and the import path `dev` changes for the backend."""
    saved = dict(os.environ)
    monkeypatch.setattr(sys, "path", list(sys.path))
    yield
    os.environ.clear()
    os.environ.update(saved)


@pytest.fixture
def served(monkeypatch, process):
    """What uvicorn.run was called with, and the environment and path the backend starts with."""
    calls = []

    def run(app, **settings):
        calls.append({"app": app, "settings": settings, "environment": dict(os.environ), "path": list(sys.path)})

    monkeypatch.setattr(uvicorn, "run", run)
    return calls


@pytest.fixture
def database(monkeypatch):
    """The local database `dev` connects to, a fake with Weather's two roles."""
    connection = FakeConnection()
    urls = []

    def connect(url):
        urls.append(url)
        return connection

    monkeypatch.setattr(development_database, "connect", connect)
    connection.urls = urls
    return connection


def _dev(source, runtime_file, *options):
    return main(["dev", str(source), "--runtime-file", str(runtime_file), *options])


def _assert_no_secret(captured):
    printed = captured.out + captured.err
    for secret in SECRETS:
        assert secret not in printed
    assert not re.search(r"esp-[A-Za-z0-9_-]{43}", printed)


# Usage errors.


def test_a_source_without_a_backend_is_a_usage_error(plugin_source, runtime_file, served, capsys):
    frontend_only, _ = plugin_source

    assert _dev(frontend_only, runtime_file) == 2
    assert "has no backend section" in capsys.readouterr().err
    assert served == []


def test_a_directory_without_a_manifest_is_a_usage_error(tmp_path, runtime_file, served, capsys):
    assert _dev(tmp_path / "downloads", runtime_file) == 2
    assert "is not a plugin source directory" in capsys.readouterr().err


def test_a_runtime_file_inside_the_source_is_refused(source, runtime_file, served, capsys):
    inside = source / "notes" / "weather-development-runtime.json"
    inside.parent.mkdir()
    inside.write_bytes(runtime_file.read_bytes())

    assert _dev(source, inside) == 2

    captured = capsys.readouterr()
    assert "keep it outside your plugin's source: it holds keys and secret settings" in captured.err
    _assert_no_secret(captured)
    assert served == []


def test_a_runtime_file_reached_through_a_link_into_the_source_is_refused(source, runtime_file, tmp_path, served, capsys):
    inside = source / "weather-development-runtime.json"
    inside.write_bytes(runtime_file.read_bytes())
    link = tmp_path / "downloads" / "link.json"
    link.symlink_to(inside)

    assert _dev(source, link) == 2
    assert "keep it outside your plugin's source" in capsys.readouterr().err


def test_a_runtime_file_copied_into_the_backend_is_refused_by_name(source, runtime_file, served, capsys):
    (source / "backend" / "weather-development-runtime.json").write_bytes(runtime_file.read_bytes())

    assert _dev(source, runtime_file) == 2

    captured = capsys.readouterr()
    assert (
        "package.backend/weather-development-runtime.json: holds an EpicStaff key or runtime file; never package it"
        in captured.out
    )
    assert "keep it outside your plugin's source" in captured.err
    _assert_no_secret(captured)
    assert served == []


def test_a_runtime_file_for_another_plugin_is_refused(source, tmp_path, served, capsys):
    other = tmp_path / "chat-development-runtime.json"
    write_runtime_file(other, signer=ContextSigner(plugin_identifier="chat"))

    assert _dev(source, other) == 2
    assert "is for the plugin chat, not weather" in capsys.readouterr().err


def test_apply_migrations_needs_a_database_url(source, runtime_file, served, capsys):
    assert _dev(source, runtime_file, "--apply-migrations") == 2
    assert "--apply-migrations needs --database-url" in capsys.readouterr().err


@pytest.mark.parametrize("options", [["--database-url", DATABASE_URL], ["--database-url", DATABASE_URL, "--apply-migrations"]])
def test_database_options_need_a_manifest_with_a_database(source, runtime_file, manifest, served, capsys, options):
    del manifest["database"]
    _write_manifest(source, manifest)

    assert _dev(source, runtime_file, *options) == 2
    assert "weather's manifest has no database section" in capsys.readouterr().err


def test_a_database_url_that_is_not_postgresql_is_refused_without_repeating_it(source, runtime_file, served, capsys):
    assert _dev(source, runtime_file, "--database-url", f"mysql://weather_app:{DATABASE_PASSWORD}@localhost/db") == 2

    captured = capsys.readouterr()
    assert "--database-url must be a postgresql:// URL" in captured.err
    _assert_no_secret(captured)


@pytest.mark.parametrize("port", ["80", "1023", "65536", "eighty", "٨٠٠١"])
def test_a_port_outside_1024_to_65535_is_a_usage_error(source, runtime_file, served, capsys, port):
    with pytest.raises(SystemExit) as exited:
        _dev(source, runtime_file, "--port", port)

    assert exited.value.code == 2
    assert "must be a port number from 1024 to 65535" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["0.0.0.0.0", "example.com", ""])
def test_a_host_that_is_not_an_address_or_localhost_is_a_usage_error(source, runtime_file, served, capsys, host):
    with pytest.raises(SystemExit) as exited:
        _dev(source, runtime_file, "--host", host)

    assert exited.value.code == 2
    assert "must be an IP address or localhost" in capsys.readouterr().err


# Start failures.


def test_an_invalid_runtime_file_fails_with_where_it_is_wrong(source, runtime_file, served, capsys):
    document = json.loads(runtime_file.read_text())
    document["service_accounts"]["3"]["key"] = "esp-short"
    del document["jwks"]
    runtime_file.write_text(json.dumps(document))

    assert _dev(source, runtime_file) == 1

    captured = capsys.readouterr()
    assert "runtime.jwks: Field required" in captured.err
    assert "runtime.service_accounts.3.key: String should match pattern" in captured.err
    assert "esp-short" not in captured.err
    _assert_no_secret(captured)
    assert served == []


def test_a_missing_runtime_file_fails(source, tmp_path, served, capsys):
    assert _dev(source, tmp_path / "missing.json") == 1
    assert "cannot read" in capsys.readouterr().err


def test_an_entrypoint_whose_module_is_missing_fails(source, runtime_file, served, capsys):
    (source / "backend" / "src" / "weather_plugin" / "app.py").unlink()

    assert _dev(source, runtime_file) == 1
    assert "manifest.backend.entrypoint: names a module that is neither backend/src/weather_plugin/app.py" in capsys.readouterr().out


def test_a_lock_this_environment_does_not_satisfy_names_what_to_install(source, runtime_file, served, capsys):
    lock = source / "backend" / "requirements.lock"
    lock.write_text(lock.read_text() + _lock_line("fastapi-that-is-not-installed", "1.0") + _lock_line("tzdata-only-on-windows", "1.0").replace(" --hash", " ; sys_platform == 'win32' --hash"))

    assert _dev(source, runtime_file) == 1

    error = capsys.readouterr().err
    assert "install the backend's lock in this environment (backend/requirements.lock); not installed: fastapi-that-is-not-installed" in error
    assert "tzdata" not in error
    assert served == []


def test_without_uvicorn_it_says_what_to_install(source, runtime_file, served, monkeypatch, capsys):
    (source / "backend" / "requirements.lock").write_text(_lock_line("psycopg", importlib.metadata.version("psycopg")))
    monkeypatch.setitem(sys.modules, "uvicorn", None)

    assert _dev(source, runtime_file) == 1
    assert "uvicorn is not installed: install the backend's lock in this environment" in capsys.readouterr().err


def test_a_database_with_unsuitable_roles_fails_with_the_sql_and_no_password(source, runtime_file, database, served, capsys):
    database.login_role = ("postgres", True, False)

    assert _dev(source, runtime_file, "--database-url", DATABASE_URL) == 1

    captured = capsys.readouterr()
    assert "row-level security would not apply as on EpicStaff" in captured.err
    assert "CREATE ROLE weather_app LOGIN PASSWORD '<password>';" in captured.err
    _assert_no_secret(captured)
    assert database.closed
    assert served == []


def test_a_failing_migration_fails_the_start(source, runtime_file, database, served, capsys):
    (source / "database" / "migrations" / "004_broken.sql").write_text("DO $$ BEGIN RAISE EXCEPTION 'boom'; END $$;\n")

    assert _dev(source, runtime_file, "--database-url", DATABASE_URL, "--apply-migrations") == 1

    assert "004_broken.sql line 1: [P0001] boom" in capsys.readouterr().err
    assert database.closed
    assert served == []


@pytest.mark.parametrize(("code", "expected"), [(3, 1), (1, 1), (0, 0), (None, 0)])
def test_uvicorn_exiting_by_itself_is_a_start_failure(source, runtime_file, process, monkeypatch, code, expected):
    def run(app, **settings):
        raise SystemExit(code)

    monkeypatch.setattr(uvicorn, "run", run)

    assert _dev(source, runtime_file) == expected


# What it runs.


def test_the_backend_is_served_by_the_nodes_app_factory_with_reload(source, runtime_file, served):
    assert _dev(source, runtime_file) == 0

    (call,) = served
    assert call["app"] == "epicstaff_plugin.serve:create_app"
    assert call["settings"] == {
        "factory": True,
        "host": "127.0.0.1",
        "port": 8001,
        "reload": True,
        "reload_dirs": [str((source / "backend" / "src").resolve())],
        "proxy_headers": False,
        "server_header": False,
        "lifespan": "on",
    }


def test_the_host_port_and_no_reload_are_passed_on(source, runtime_file, served):
    assert _dev(source, runtime_file, "--port", "9001", "--host", "localhost", "--no-reload") == 0

    (call,) = served
    assert (call["settings"]["host"], call["settings"]["port"], call["settings"]["reload"]) == ("localhost", 9001, False)
    assert "reload_dirs" not in call["settings"]


def test_the_backend_environment_is_what_the_node_sets_from_this_source(source, runtime_file, manifest, served, monkeypatch):
    monkeypatch.setenv(LISTEN_FD_ENVIRONMENT_VARIABLE, "3")
    monkeypatch.setenv(runtime_contract.DATABASE_URL_ENVIRONMENT_VARIABLE, "postgresql://left@over/db")
    monkeypatch.setenv(runtime_contract.DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE, "9")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    monkeypatch.setenv("PYTHONPATH", "/inherited")
    before = dict(os.environ)

    assert _dev(source, runtime_file) == 0

    (call,) = served
    backend_source = str((source / "backend" / "src").resolve())
    expected = {
        name: value
        for name, value in before.items()
        if name
        not in (
            LISTEN_FD_ENVIRONMENT_VARIABLE,
            runtime_contract.DATABASE_URL_ENVIRONMENT_VARIABLE,
            runtime_contract.DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE,
        )
    }
    expected.update(
        {
            PORT_ENVIRONMENT_VARIABLE: "8001",
            runtime_contract.PLUGIN_IDENTIFIER_ENVIRONMENT_VARIABLE: "weather",
            runtime_contract.PLUGIN_VERSION_ENVIRONMENT_VARIABLE: manifest["version"],
            runtime_contract.ENTRYPOINT_ENVIRONMENT_VARIABLE: "weather_plugin.app:app",
            runtime_contract.RUNTIME_FILE_ENVIRONMENT_VARIABLE: str(runtime_file.resolve()),
            runtime_contract.EPICSTAFF_API_URL_ENVIRONMENT_VARIABLE: DEVELOPMENT_API_URL,
            runtime_contract.EPICSTAFF_PUBLIC_URL_ENVIRONMENT_VARIABLE: "http://epicstaff.localhost",
            runtime_contract.PLUGIN_PUBLIC_URL_ENVIRONMENT_VARIABLE: "http://weather.plugins.epicstaff.localhost",
            "PYTHONPATH": f"{backend_source}{os.pathsep}/inherited",
        }
    )
    assert call["environment"] == expected
    assert call["path"][0] == backend_source


def test_the_environment_names_are_the_ones_the_node_sets():
    assert (
        runtime_contract.PORT_ENVIRONMENT_VARIABLE,
        runtime_contract.LISTEN_FD_ENVIRONMENT_VARIABLE,
        runtime_contract.PLUGIN_IDENTIFIER_ENVIRONMENT_VARIABLE,
        runtime_contract.PLUGIN_VERSION_ENVIRONMENT_VARIABLE,
        runtime_contract.ENTRYPOINT_ENVIRONMENT_VARIABLE,
        runtime_contract.RUNTIME_FILE_ENVIRONMENT_VARIABLE,
        runtime_contract.EPICSTAFF_API_URL_ENVIRONMENT_VARIABLE,
        runtime_contract.EPICSTAFF_PUBLIC_URL_ENVIRONMENT_VARIABLE,
        runtime_contract.PLUGIN_PUBLIC_URL_ENVIRONMENT_VARIABLE,
    ) == (
        "PORT",
        "EPICSTAFF_PLUGIN_LISTEN_FD",
        "EPICSTAFF_PLUGIN_IDENTIFIER",
        "EPICSTAFF_PLUGIN_VERSION",
        "EPICSTAFF_PLUGIN_ENTRYPOINT",
        "EPICSTAFF_PLUGIN_RUNTIME_FILE",
        "EPICSTAFF_API_URL",
        "EPICSTAFF_PUBLIC_URL",
        "EPICSTAFF_PLUGIN_PUBLIC_URL",
    )


def test_serve_reads_the_same_environment_names():
    assert (
        serve.ENTRYPOINT_ENVIRONMENT_VARIABLE,
        serve.PORT_ENVIRONMENT_VARIABLE,
        serve.LISTEN_FD_ENVIRONMENT_VARIABLE,
    ) == (
        runtime_contract.ENTRYPOINT_ENVIRONMENT_VARIABLE,
        runtime_contract.PORT_ENVIRONMENT_VARIABLE,
        runtime_contract.LISTEN_FD_ENVIRONMENT_VARIABLE,
    )


def test_a_database_url_gives_the_backend_the_database_with_the_manifests_connections(source, runtime_file, database, served):
    assert _dev(source, runtime_file, "--database-url", DATABASE_URL) == 0

    environment = served[0]["environment"]
    assert environment[runtime_contract.DATABASE_URL_ENVIRONMENT_VARIABLE] == DATABASE_URL
    assert environment[runtime_contract.DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE] == "3"
    # The roles are checked even without --apply-migrations; nothing is applied.
    assert database.queried_job_roles == ["weather_job"]
    assert not database.ledger_created
    assert database.closed


def test_without_a_connection_limit_in_the_manifest_the_backend_gets_five(source, runtime_file, manifest, database, served):
    del manifest["limits"]["db_connections"]
    _write_manifest(source, manifest)

    assert _dev(source, runtime_file, "--database-url", DATABASE_URL) == 0
    assert served[0]["environment"][runtime_contract.DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE] == "5"


def test_apply_migrations_applies_the_sources_migrations_before_the_backend_starts(source, runtime_file, database, served, capsys):
    assert _dev(source, runtime_file, "--database-url", DATABASE_URL, "--apply-migrations") == 0

    migrations = sorted(path.name for path in (source / "database" / "migrations").glob("*.sql"))
    assert list(database.ledger) == migrations
    output = capsys.readouterr().out
    assert (
        "Database: postgresql://weather_app:***@localhost:5432/weather_development "
        f"(applied {len(migrations)} migrations: {', '.join(migrations)}; 0 already applied)"
    ) in output


# What it prints.


def test_it_prints_where_to_point_epicstaff_and_how_it_differs_from_the_node(source, runtime_file, manifest, served, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "darwin")

    assert _dev(source, runtime_file) == 0

    captured = capsys.readouterr()
    lines = captured.out.splitlines()
    version = manifest["version"]
    assert lines[:4] == [
        f"Weather (weather) {version} from {source}",
        f"Installed in EpicStaff: {version}",
        "Backend: http://127.0.0.1:8001",
        "Database: none; the manifest has a database section, so pass --database-url",
    ]
    assert "In EpicStaff: Plugins → Weather → Development → Backend port 8001 → Save" in lines
    assert "Then open http://epicstaff.localhost/plugins/weather" in lines
    assert "Keys for: E2E Acme (3), E2E Cobalt (7)" in lines
    assert (
        "Download the file again to the same path after granting another organization or after a suspension."
        in lines
    )
    assert lines[lines.index("How this backend differs from the plugin node:") + 1 :][:4] == [
        "  - no outbound-host allow-list: requests leave through this machine's network",
        "  - the database is the one you pass, not the plugin's",
        "  - hooks run on the installed version",
        "  - public paths, settings, access and permissions are the installed version's",
    ]
    assert not [line for line in lines if line.startswith(("note:", "warning:", "On Linux"))]
    _assert_no_secret(captured)


def test_a_source_version_that_differs_from_the_installed_one_is_noted(source, runtime_file, manifest, served, capsys):
    manifest["version"] = "9.0.0"
    _write_manifest(source, manifest)

    assert _dev(source, runtime_file) == 0

    assert "note: the source is 9.0.0, EpicStaff runs 0.7.0: the installed version's manifest applies" in capsys.readouterr().out


def test_public_paths_that_differ_from_the_installed_ones_are_noted(source, runtime_file, manifest, served, capsys):
    manifest["public_paths"] = manifest["public_paths"][:1]
    _write_manifest(source, manifest)

    assert _dev(source, runtime_file) == 0

    assert "note: the source's public paths differ from the installed version's" in capsys.readouterr().out


def test_a_runtime_file_readable_by_others_is_warned_about(source, runtime_file, served, capsys):
    runtime_file.chmod(0o644)

    assert _dev(source, runtime_file) == 0

    assert f"warning: {runtime_file.resolve()} is readable by other users of this machine" in capsys.readouterr().out


def test_a_runtime_file_whose_api_is_not_on_this_machine_is_warned_about(source, runtime_file, served, capsys):
    document = json.loads(runtime_file.read_text())
    document["epicstaff_api_url"] = "http://epicstaff-api:8081/api/"
    runtime_file.write_text(json.dumps(document))

    assert _dev(source, runtime_file) == 0

    assert (
        "warning: the runtime file's EpicStaff API address http://epicstaff-api:8081/api/ is not on this machine"
        in capsys.readouterr().out
    )


def test_a_runtime_file_without_keys_says_how_to_get_them(source, runtime_file, served, capsys):
    document = json.loads(runtime_file.read_text())
    document["service_accounts"] = {}
    runtime_file.write_text(json.dumps(document))

    assert _dev(source, runtime_file) == 0

    assert "Keys for: no organization; grant the plugin to one, then download the file again" in capsys.readouterr().out


def test_on_linux_it_says_where_to_listen(source, runtime_file, served, monkeypatch, capsys):
    monkeypatch.setattr(sys, "platform", "linux")

    assert _dev(source, runtime_file) == 0

    assert "On Linux, EpicStaff's containers reach this machine at the Docker bridge address" in capsys.readouterr().out


def test_an_environment_that_differs_from_the_lock_is_noted(source, runtime_file, served, capsys):
    (source / "backend" / "requirements.lock").write_text(_lock_line("uvicorn", "0.0.1"))

    assert _dev(source, runtime_file) == 0

    installed = importlib.metadata.version("uvicorn")
    assert f"note: this environment differs from backend/requirements.lock: uvicorn {installed} (lock 0.0.1)" in capsys.readouterr().out


def test_nothing_secret_is_printed_on_a_full_start(source, runtime_file, database, served, capsys):
    assert _dev(source, runtime_file, "--database-url", DATABASE_URL, "--apply-migrations") == 0

    captured = capsys.readouterr()
    assert "Database: postgresql://weather_app:***@localhost:5432/weather_development" in captured.out
    _assert_no_secret(captured)


def test_owned_tables_whose_policies_do_not_apply_here_are_warned_about(source, runtime_file, database, served, capsys):
    database.exempt_tables = [("weather", "saved_places"), ("weather", "popup_results")]

    assert _dev(source, runtime_file, "--database-url", DATABASE_URL, "--apply-migrations") == 0

    assert (
        "warning: weather_app owns these tables and they do not FORCE ROW LEVEL SECURITY, so their row-level "
        "security policies do not apply to this backend; on EpicStaff they do: weather.saved_places, "
        "weather.popup_results"
    ) in capsys.readouterr().out


def test_without_such_tables_there_is_no_row_level_security_warning(source, runtime_file, database, served, capsys):
    assert _dev(source, runtime_file, "--database-url", DATABASE_URL) == 0

    assert "FORCE ROW LEVEL SECURITY" not in capsys.readouterr().out


needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")


def git(directory, *arguments):
    subprocess.run(["git", "-C", str(directory), *arguments], check=True, capture_output=True)


@needs_git
def test_a_runtime_file_in_a_git_work_tree_that_does_not_ignore_it_is_warned_about_once(tmp_path, source, runtime_file, served, capsys):
    git(tmp_path, "init", "--quiet")

    assert _dev(source, runtime_file) == 0

    output = capsys.readouterr().out
    warning = f"warning: {runtime_file.resolve()} is in the git work tree {tmp_path.resolve()} and no ignore rule covers it"
    assert output.count(warning) == 1


@needs_git
def test_a_runtime_file_a_git_ignore_rule_covers_is_not_warned_about(tmp_path, source, runtime_file, served, capsys):
    git(tmp_path, "init", "--quiet")
    (tmp_path / ".gitignore").write_text("downloads/\n")

    assert _dev(source, runtime_file) == 0

    assert "git work tree" not in capsys.readouterr().out


@needs_git
def test_a_runtime_file_outside_any_git_work_tree_is_not_warned_about(runtime_file):
    assert development.unignored_git_work_tree(runtime_file.resolve()) is None


def test_a_host_given_as_an_ipv6_address_is_shown_in_brackets(source, runtime_file, served, capsys):
    assert _dev(source, runtime_file, "--host", "::1") == 0

    assert "Backend: http://[::1]:8001" in capsys.readouterr().out


def test_the_development_module_uses_the_sdk_constants_not_its_own_names():
    text = Path(development.__file__).read_text()

    for literal in ('"EPICSTAFF_', '"DATABASE_URL"', '"PORT"'):
        assert literal not in text
