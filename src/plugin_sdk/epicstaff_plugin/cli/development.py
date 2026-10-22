"""`epicstaff-plugin dev`: serve a plugin's backend from its source, on this machine.

A SuperAdmin of a deployment in plugin development mode points the plugin's development target
at a port of this machine; EpicStaff then sends the plugin's gateway traffic here instead of to
the plugin node. This command serves the backend there as the node would:
`epicstaff_plugin.serve:create_app`, so health, hooks and the gateway-context check come before
the plugin's own app, with uvicorn reloading it whenever `backend/src` changes.

It needs the development runtime file the SuperAdmin downloads: its development keys let the
backend call EpicStaff's API on this machine's loopback, and its signing keys verify the gateway's
contexts. The file holds those keys and the plugin's secret settings, so it must stay outside the
source, and nothing here ever prints a key, a secret setting or a database password.

Run it in the plugin's own environment, with the backend's lock installed: the plugin's
dependencies (uvicorn, its web framework, its database driver) are not the SDK's.
"""

import argparse
import importlib.metadata
import ipaddress
import os
import stat
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from packaging.markers import default_environment
from packaging.version import InvalidVersion, Version

from epicstaff_plugin.cli import development_database
from epicstaff_plugin.cli.development_database import (
    DatabaseUrl,
    DevelopmentDatabaseError,
    MigrationRun,
)
from epicstaff_plugin.cli.output import EXIT_OK, UsageError, print_error, print_problems
from epicstaff_plugin.contracts.manifest import MANIFEST_FILE_NAME, PluginManifest
from epicstaff_plugin.contracts.runtime import (
    DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE,
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    ENTRYPOINT_ENVIRONMENT_VARIABLE,
    EPICSTAFF_API_URL_ENVIRONMENT_VARIABLE,
    EPICSTAFF_PUBLIC_URL_ENVIRONMENT_VARIABLE,
    LISTEN_FD_ENVIRONMENT_VARIABLE,
    PLUGIN_IDENTIFIER_ENVIRONMENT_VARIABLE,
    PLUGIN_PUBLIC_URL_ENVIRONMENT_VARIABLE,
    PLUGIN_VERSION_ENVIRONMENT_VARIABLE,
    PORT_ENVIRONMENT_VARIABLE,
    RUNTIME_FILE_ENVIRONMENT_VARIABLE,
    RuntimeFile,
)
from epicstaff_plugin.package_layout import (
    BACKEND_REQUIREMENTS,
    BACKEND_SOURCE_DIRECTORY,
    entrypoint_module_paths,
)
from epicstaff_plugin.package_source import PackageSource, collect_source
from epicstaff_plugin.problems import MANIFEST_LOC, PackageProblemsError, Problem, archive_file_loc
from epicstaff_plugin.requirements_lock import RequirementsLock, parse_requirements_lock
from epicstaff_plugin.runtime.runtime_config import RuntimeConfig, RuntimeConfigError

DEFAULT_PORT = 8001
DEFAULT_HOST = "127.0.0.1"
MIN_PORT = 1024
MAX_PORT = 65535
# EpicStaff's default for a manifest without `limits.db_connections`.
DEFAULT_DATABASE_CONNECTIONS = 5
APP_FACTORY = "epicstaff_plugin.serve:create_app"
PYTHON_PATH_ENVIRONMENT_VARIABLE = "PYTHONPATH"
EXIT_START_FAILED = 1
KEEP_OUTSIDE_SOURCE = "keep it outside your plugin's source: it holds keys and secret settings"
# Variables the backend must not inherit: `serve` would use the socket instead of binding, and
# the database variables come only from --database-url.
_NOT_INHERITED = (
    LISTEN_FD_ENVIRONMENT_VARIABLE,
    DATABASE_URL_ENVIRONMENT_VARIABLE,
    DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE,
)


def development_port(value: str) -> int:
    """argparse type of `--port`: a port from 1024 to 65535."""
    if not (value.isascii() and value.isdecimal()) or not MIN_PORT <= int(value) <= MAX_PORT:
        raise argparse.ArgumentTypeError(f"must be a port number from {MIN_PORT} to {MAX_PORT}")
    return int(value)


def development_host(value: str) -> str:
    """argparse type of `--host`: an IP address or `localhost`."""
    if value == "localhost":
        return value
    try:
        ipaddress.ip_address(value)
    except ValueError:
        raise argparse.ArgumentTypeError("must be an IP address or localhost") from None
    return value


@dataclass(frozen=True)
class DatabaseState:
    """The database given with --database-url, as the start text describes it."""

    url: DatabaseUrl
    migrations: MigrationRun | None
    """What --apply-migrations did; None without it."""


@dataclass(frozen=True)
class LockDifference:
    name: str
    installed: str
    locked: str


def develop(
    source_directory: Path,
    runtime_file: Path,
    *,
    port: int = DEFAULT_PORT,
    host: str = DEFAULT_HOST,
    reload: bool = True,
    database_url: str | None = None,
    apply_migrations: bool = False,
) -> int:
    """Check everything `dev` needs, then serve the backend until stopped; return the exit code.

    Raises:
        UsageError: The command was called wrongly (exit 2): no plugin source or no backend, a
            runtime file inside the source or for another plugin, a key or runtime file in the
            source, or database options that do not fit the manifest.
    """
    source = _plugin_source(source_directory)
    if source is None:
        return EXIT_START_FAILED
    manifest = source.manifest
    if manifest.backend is None:
        raise UsageError(f"{manifest.id}'s manifest has no backend section; dev serves a backend")
    if secret_problems := source.secret_problems():
        print_problems(secret_problems)
        raise UsageError(
            f"a file of the source holds an EpicStaff key or runtime file: {KEEP_OUTSIDE_SOURCE}"
        )
    runtime_path = runtime_file.resolve()
    if runtime_path.is_relative_to(source_directory.resolve()):
        raise UsageError(
            f"--runtime-file {runtime_file} is inside {source_directory}: {KEEP_OUTSIDE_SOURCE}"
        )
    url = _database_url(manifest, database_url, apply_migrations)

    try:
        runtime = RuntimeConfig.load(runtime_path).document
    except RuntimeConfigError as error:
        print_error(str(error))
        return EXIT_START_FAILED
    if runtime.plugin.identifier != manifest.id:
        raise UsageError(
            f"--runtime-file is for the plugin {runtime.plugin.identifier}, not {manifest.id}: "
            f"download it from Plugins → {manifest.name} → Development"
        )
    if problems := _entrypoint_problems(source):
        print_problems(problems)
        return EXIT_START_FAILED
    try:
        lock = parse_requirements_lock(_lock_file(source).read_bytes())
    except PackageProblemsError as error:
        print_problems(error.problems)
        return EXIT_START_FAILED
    missing, differing = lock_differences(lock)
    if missing:
        print_error(
            f"install the backend's lock in this environment ({BACKEND_REQUIREMENTS}); "
            f"not installed: {', '.join(missing)}"
        )
        return EXIT_START_FAILED
    # Imported here: uvicorn is a dependency of the plugin's lock, not of the SDK.
    try:
        import uvicorn
    except ImportError:
        print_error("uvicorn is not installed: install the backend's lock in this environment")
        return EXIT_START_FAILED

    database = None
    if url is not None:
        try:
            database = _prepare_database(url, source, apply_migrations)
        except DevelopmentDatabaseError as error:
            print_error(str(error))
            return EXIT_START_FAILED

    backend_source = (source_directory / BACKEND_SOURCE_DIRECTORY).resolve()
    _replace_environment(
        development_environment(
            os.environ,
            manifest=manifest,
            runtime=runtime,
            runtime_file=runtime_path,
            backend_source=backend_source,
            port=port,
            database_url=url,
        )
    )
    # For a run without reload, which imports the plugin in this process; a reloading run's
    # worker process starts with this path too.
    sys.path.insert(0, str(backend_source))
    for line in start_text(
        manifest,
        runtime,
        source_directory=source_directory,
        runtime_file=runtime_path,
        host=host,
        port=port,
        database=database,
        lock_differences=differing,
    ):
        print(line)
    sys.stdout.flush()

    settings: dict[str, object] = {
        "factory": True,
        "host": host,
        "port": port,
        "reload": reload,
        # As on the node: the gateway is the only proxy in front, and the backend never needs the
        # client's address from forwarded headers.
        "proxy_headers": False,
        "server_header": False,
        "lifespan": "on",
    }
    if reload:
        settings["reload_dirs"] = [str(backend_source)]
    try:
        uvicorn.run(APP_FACTORY, **settings)
    except SystemExit as stopped:
        # uvicorn exits by itself when it cannot start (the port is taken, the app does not
        # import); a reloading run instead waits for the next change.
        return EXIT_OK if stopped.code in (None, 0) else EXIT_START_FAILED
    return EXIT_OK


def development_environment(
    base: Mapping[str, str],
    *,
    manifest: PluginManifest,
    runtime: RuntimeFile,
    runtime_file: Path,
    backend_source: Path,
    port: int,
    database_url: DatabaseUrl | None,
) -> dict[str, str]:
    """The backend's environment: `base` with what the node would set, from this source.

    Everything else in `base` is inherited, proxy variables included.
    """
    environment = {name: value for name, value in base.items() if name not in _NOT_INHERITED}
    inherited_path = base.get(PYTHON_PATH_ENVIRONMENT_VARIABLE)
    environment.update(
        {
            PORT_ENVIRONMENT_VARIABLE: str(port),
            PLUGIN_IDENTIFIER_ENVIRONMENT_VARIABLE: manifest.id,
            PLUGIN_VERSION_ENVIRONMENT_VARIABLE: manifest.version,
            ENTRYPOINT_ENVIRONMENT_VARIABLE: manifest.backend.entrypoint,
            RUNTIME_FILE_ENVIRONMENT_VARIABLE: str(runtime_file),
            EPICSTAFF_API_URL_ENVIRONMENT_VARIABLE: runtime.epicstaff_api_url,
            EPICSTAFF_PUBLIC_URL_ENVIRONMENT_VARIABLE: runtime.epicstaff_public_url,
            PLUGIN_PUBLIC_URL_ENVIRONMENT_VARIABLE: runtime.public_url,
            PYTHON_PATH_ENVIRONMENT_VARIABLE: os.pathsep.join(
                [str(backend_source), *([inherited_path] if inherited_path else [])]
            ),
        }
    )
    if database_url is not None:
        limits = manifest.limits
        connections = (limits.db_connections if limits else None) or DEFAULT_DATABASE_CONNECTIONS
        environment[DATABASE_URL_ENVIRONMENT_VARIABLE] = database_url.value
        environment[DATABASE_CONNECTIONS_ENVIRONMENT_VARIABLE] = str(connections)
    return environment


def lock_differences(lock: RequirementsLock) -> tuple[list[str], list[LockDifference]]:
    """The lock's pins for this interpreter that are not installed here, and those installed at
    another version."""
    environment = default_environment()
    missing = []
    differing = []
    for requirement in lock.requirements:
        if not requirement.applies_to(environment):
            continue
        try:
            installed = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            missing.append(requirement.name)
            continue
        try:
            same = Version(installed) == requirement.version
        except InvalidVersion:
            same = False
        if not same:
            differing.append(LockDifference(requirement.name, installed, str(requirement.version)))
    return missing, differing


def start_text(
    manifest: PluginManifest,
    runtime: RuntimeFile,
    *,
    source_directory: Path,
    runtime_file: Path,
    host: str,
    port: int,
    database: DatabaseState | None,
    lock_differences: list[LockDifference],
) -> list[str]:
    """What `dev` prints once before it starts: where to point EpicStaff, and how this differs
    from the plugin node. Never a key, a secret setting or a database password."""
    installed = runtime.plugin.version
    shown_host = f"[{host}]" if ":" in host else host
    epicstaff = runtime.epicstaff_public_url.rstrip("/")
    lines = [f"{manifest.name} ({manifest.id}) {manifest.version} from {source_directory}"]
    lines.append(f"Installed in EpicStaff: {installed}")
    if manifest.version != installed:
        lines.append(
            f"note: the source is {manifest.version}, EpicStaff runs {installed}: the installed "
            "version's manifest applies"
        )
    lines.append(f"Backend: http://{shown_host}:{port}")
    lines.append(_database_line(manifest, database))
    lines += [
        "",
        f"In EpicStaff: Plugins → {manifest.name} → Development → Backend port {port} → Save",
        f"Then open {epicstaff}/plugins/{manifest.id}",
        "",
        f"Keys for: {_organizations(runtime)}",
        (
            "Download the file again to the same path after granting another organization or "
            "after a suspension."
        ),
        "",
        "How this backend differs from the plugin node:",
        "  - no outbound-host allow-list: requests leave through this machine's network",
        "  - the database is the one you pass, not the plugin's"
        + (" (its login role also owns the tables)" if database else ""),
        "  - hooks run on the installed version",
        "  - public paths, settings, access and permissions are the installed version's",
    ]
    if manifest.public_paths != runtime.public_paths:
        lines.append(
            "note: the source's public paths differ from the installed version's; the gateway "
            "applies the installed ones"
        )
    if lock_differences:
        lines.append(
            f"note: this environment differs from {BACKEND_REQUIREMENTS}: "
            + ", ".join(
                f"{difference.name} {difference.installed} (lock {difference.locked})"
                for difference in lock_differences
            )
        )
    if not _is_loopback_url(runtime.epicstaff_api_url):
        lines.append(
            f"warning: the runtime file's EpicStaff API address {runtime.epicstaff_api_url} is not "
            f"on this machine; download the development runtime file from Plugins → "
            f"{manifest.name} → Development"
        )
    if os.name == "posix" and runtime_file.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
        lines.append(
            f"warning: {runtime_file} is readable by other users of this machine; "
            f"restrict it with chmod 600 {runtime_file}"
        )
    if sys.platform.startswith("linux"):
        lines.append(
            "On Linux, EpicStaff's containers reach this machine at the Docker bridge address: "
            "listen there with --host (for example --host 172.17.0.1)"
        )
    return lines


def _plugin_source(source_directory: Path) -> PackageSource | None:
    if not (source_directory / MANIFEST_FILE_NAME).is_file():
        raise UsageError(
            f"{source_directory} is not a plugin source directory: it has no {MANIFEST_FILE_NAME}"
        )
    try:
        return collect_source(source_directory, None)
    except PackageProblemsError as error:
        print_problems(error.problems)
        return None


def _database_url(
    manifest: PluginManifest, database_url: str | None, apply_migrations: bool
) -> DatabaseUrl | None:
    if apply_migrations and database_url is None:
        raise UsageError("--apply-migrations needs --database-url")
    if database_url is None:
        return None
    if manifest.database is None:
        raise UsageError(
            f"--database-url is for a plugin with a database; {manifest.id}'s manifest has no "
            "database section"
        )
    try:
        return DatabaseUrl.parse(database_url)
    except ValueError as error:
        raise UsageError(str(error)) from None


def _entrypoint_problems(source: PackageSource) -> list[Problem]:
    candidates = entrypoint_module_paths(source.manifest.backend.entrypoint)
    if any(source.file(candidate) for candidate in candidates):
        return []
    return [
        Problem(
            f"{MANIFEST_LOC}.backend.entrypoint",
            f"names a module that is neither {candidates[0]} nor {candidates[1]}",
        )
    ]


def _lock_file(source: PackageSource) -> Path:
    file = source.file(BACKEND_REQUIREMENTS)
    if file is None:
        raise PackageProblemsError([Problem(archive_file_loc(BACKEND_REQUIREMENTS), "is missing")])
    return file.source


def _prepare_database(
    url: DatabaseUrl, source: PackageSource, apply_migrations: bool
) -> DatabaseState:
    # Read before connecting, so a source the node would refuse never touches the database.
    migrations = development_database.source_migrations(source) if apply_migrations else None
    connection = development_database.connect(url)
    try:
        roles = development_database.check_roles(connection, source.manifest.id)
        run = None
        if migrations is not None:
            run = development_database.apply_migrations(connection, roles, migrations)
    finally:
        connection.close()
    return DatabaseState(url=url, migrations=run)


def _database_line(manifest: PluginManifest, database: DatabaseState | None) -> str:
    if database is None:
        if manifest.database is None:
            return "Database: none (the manifest has no database section)"
        return "Database: none; the manifest has a database section, so pass --database-url"
    run = database.migrations
    if run is None:
        return f"Database: {database.url.shown} (no migrations applied: pass --apply-migrations)"
    applied = f"applied {len(run.applied)} migrations" + (
        f": {', '.join(run.applied)}" if run.applied else ""
    )
    return f"Database: {database.url.shown} ({applied}; {run.already_applied} already applied)"


def _organizations(runtime: RuntimeFile) -> str:
    entries = sorted(
        runtime.service_accounts.items(),
        key=lambda item: (item[1].org_name.casefold(), int(item[0])),
    )
    if not entries:
        return "no organization; grant the plugin to one, then download the file again"
    return ", ".join(f"{entry.org_name} ({org_id})" for org_id, entry in entries)


def _is_loopback_url(url: str) -> bool:
    host = urlsplit(url).hostname
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _replace_environment(environment: Mapping[str, str]) -> None:
    for name in set(os.environ) - set(environment):
        del os.environ[name]
    os.environ.update(environment)
