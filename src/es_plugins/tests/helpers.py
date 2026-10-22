"""Builders for the tests: wheels, packages, desired states, a django_app and a launcher stand-in."""

import base64
import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from epicstaff_plugin.contracts.hook_api import HookRequest, encode_hook_body
from epicstaff_plugin.package_layout import PackageFile, build_contents
from epicstaff_plugin.signing import SecretKey, sign_package
from epicstaff_plugin.testing import ContextSigner
from src.shared.models.plugin_nodes import (
    DesiredPlacement,
    DesiredRemoval,
    DesiredState,
    LedgerEntry,
    database_names_for,
)

from es_plugins.agent.launcher_client import SpawnedProcess

NODE_KEY = "n" * 64
API_URL = "http://epicstaff-api:8081/api/"
ICON_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">'
    b'<circle cx="12" cy="12" r="5" fill="currentColor"/></svg>'
)
FOREIGN_WHEEL_TAG = "cp313-cp313-win_amd64"
# Stand-ins for the secrets a hook involves: none of them may reach a log line or a report.
SERVICE_ACCOUNT_KEY = "esp-" + "k" * 40 + "abc"
HOOK_ASSERTION = "eyJhbGciOiJFZERTQSJ9.hook-assertion-never-logged.c2lnbmF0dXJl"


def make_wheel(
    directory: Path,
    name: str,
    version: str,
    *,
    tag: str = "py3-none-any",
    body: str = "",
    extra_files: dict[str, str] | None = None,
    requires: tuple[str, ...] = (),
) -> Path:
    """A minimal pure-Python wheel pip installs offline: one module named after `name`.

    `extra_files` adds members by their path in the wheel, e.g. a root `.pth` file or a
    `<name>-<version>.data/scripts/...` script. `requires` are its `Requires-Dist` lines.
    """
    distribution = name.replace("-", "_")
    dist_info = f"{distribution}-{version}.dist-info"
    metadata = f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n" + "".join(
        f"Requires-Dist: {requirement}\n" for requirement in requires
    )
    files = {
        **(extra_files or {}),
        f"{distribution}/__init__.py": body or f"VERSION = {version!r}\n",
        f"{dist_info}/METADATA": metadata,
        f"{dist_info}/WHEEL": (
            f"Wheel-Version: 1.0\nGenerator: es-plugins-tests\nRoot-Is-Purelib: true\nTag: {tag}\n"
        ),
    }
    record = []
    for path, text in files.items():
        data = text.encode()
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        record.append(f"{path},sha256={digest},{len(data)}")
    record.append(f"{dist_info}/RECORD,,")
    files[f"{dist_info}/RECORD"] = "\n".join(record) + "\n"
    directory.mkdir(parents=True, exist_ok=True)
    wheel = directory / f"{distribution}-{version}-{tag}.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for path, text in files.items():
            archive.writestr(path, text)
    return wheel


def lock_for(wheels: list[Path]) -> str:
    lines = []
    for wheel in sorted(wheels):
        name, version = wheel.name.split("-")[:2]
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        lines.append(f"{name.replace('_', '-')}=={version} --hash=sha256:{digest}")
    return "\n".join(lines) + "\n"


def backend_wheels(directory: Path) -> list[Path]:
    """Stand-ins for the two distributions every plugin lock must pin."""
    return [
        make_wheel(directory, "uvicorn", "0.52.3"),
        make_wheel(directory, "epicstaff-plugin", "0.1.0"),
    ]


def manifest(identifier="weather", version="0.2.0", python="3.13", entrypoint="weather_plugin.app:app"):
    return {
        "manifest_version": 1,
        "id": identifier,
        "version": version,
        "name": "Weather",
        "description": "Forecasts for the places your organization cares about.",
        "publisher": {"name": "EpicStaff"},
        "icon": "icon.svg",
        "platform": {"frame_protocol": 1, "gateway_context": 1, "hook_api": 1},
        "spa": {"entry": "index.html"},
        "backend": {"python": python, "entrypoint": entrypoint},
        "user_permissions": [
            {
                "action": "read",
                "description": "Open Weather and see forecasts.",
                "defaults": {"org_admin": True, "member": True, "viewer": False},
            }
        ],
    }


def package_files(wheels: list[Path], plugin_manifest: dict | None = None) -> dict[str, bytes]:
    files = {
        "manifest.json": json.dumps(plugin_manifest or manifest()).encode(),
        "icon.svg": ICON_SVG,
        "spa/index.html": b"<!doctype html><title>Weather</title>",
        "backend/src/weather_plugin/__init__.py": b"",
        "backend/src/weather_plugin/app.py": b"async def app(scope, receive, send):\n    pass\n",
        "backend/requirements.lock": lock_for(wheels).encode(),
    }
    for wheel in wheels:
        files[f"backend/wheels/{wheel.name}"] = wheel.read_bytes()
    return files


def write_package(
    path: Path,
    files: dict[str, bytes],
    *,
    identifier: str = "weather",
    version: str = "0.2.0",
    secret_key: SecretKey | None = None,
    contents: bytes | None = None,
) -> Path:
    """Write a package; CONTENTS.json lists `files` unless `contents` replaces it."""
    if contents is None:
        contents = build_contents(
            identifier,
            version,
            [
                PackageFile(path=name, size=len(data), sha256=hashlib.sha256(data).hexdigest())
                for name, data in files.items()
            ],
        )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
        archive.writestr("CONTENTS.json", contents)
        if secret_key is not None:
            archive.writestr(
                "CONTENTS.json.minisig", sign_package(contents, identifier, version, secret_key)
            )
    return path


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def placement(
    package_bytes: bytes,
    *,
    placement_id: int = 7,
    package_id: int = 12,
    identifier: str = "weather",
    version: str = "0.2.0",
    port: int = 20001,
    uid: int = 20001,
    trust: str = "untrusted",
    signer_public_key: str | None = None,
    **overrides,
) -> DesiredPlacement:
    document = {
        "placement_id": placement_id,
        "plugin_identifier": identifier,
        "desired_state": "running",
        "restart_generation": 0,
        "package": {
            "package_id": package_id,
            "version": version,
            "sha256": sha256_hex(package_bytes),
            "size": len(package_bytes),
            "trust": trust,
            "signer_public_key": signer_public_key,
        },
        "runtime": {
            "python": "3.13",
            "entrypoint": "weather_plugin.app:app",
            "port": port,
            "unix_uid": uid,
            "memory_mb": 256,
            "cpu_priority": "normal",
        },
        "credentials_revision": "c" * 64,
        "settings_revision": 0,
    }
    for key, value in overrides.items():
        section, _, field = key.partition("__")
        if field:
            document[section] = {**document[section], field: value}
        else:
            document[key] = value
    return DesiredPlacement.model_validate(document)


def database_section(identifier: str = "weather", **overrides) -> dict:
    """A desired placement's `database`, on the `plugins_db` server."""
    names = database_names_for(identifier)
    return {
        "server": {"name": "plugins_db", "host": "plugins_db", "port": 5432},
        "installation_id": "0123456789abcdef0123456789abcdef",
        "database_name": names.database,
        "owner_role": names.owner_role,
        "app_role": names.app_role,
        "job_role": names.job_role,
        "connection_limit": 3,
        "statement_timeout_seconds": 10,
        **overrides,
    }


def removal(
    *,
    placement_id: int = 7,
    identifier: str = "weather",
    uid: int = 20001,
    port: int = 20001,
    generation: int = 0,
    database: dict | None = None,
) -> DesiredRemoval:
    """A `DesiredRemoval`, without a database unless `database` (see `database_section`)."""
    return DesiredRemoval.model_validate(
        {
            "placement_id": placement_id,
            "plugin_identifier": identifier,
            "unix_uid": uid,
            "port": port,
            "generation": generation,
            "database": database,
        }
    )


def desired_state(
    placements: list[DesiredPlacement],
    node_name: str = "node-1",
    removals: list[DesiredRemoval] = (),
) -> DesiredState:
    body = {
        "format": 1,
        "node": {"name": node_name},
        "placements": [item.model_dump(mode="json") for item in placements],
        "removals": [item.model_dump(mode="json") for item in removals],
    }
    revision = sha256_hex(json.dumps(body, sort_keys=True).encode())
    return DesiredState.model_validate(
        {**body, "revision": revision, "generated_at": datetime.now(UTC).isoformat()}
    )


def service_account(org_name: str = "Acme", grant_state: str = "granting") -> dict:
    return {"key": SERVICE_ACCOUNT_KEY, "org_name": org_name, "grant_state": grant_state}


def hook_job(job_id: int = 41, organization_id: int = 3, kind: str = "install") -> dict:
    """A `DesiredHookJob` as a desired placement lists it."""
    return {"job_id": job_id, "kind": kind, "organization_id": organization_id}


def hook_body(
    job_id: int = 41,
    organization_id: int = 3,
    attempt: int = 1,
    identifier: str = "weather",
    kind: str = "install",
) -> str:
    """The exact JSON text django_app sends as a hook's body."""
    request = HookRequest(
        format=1,
        job_id=job_id,
        attempt=attempt,
        kind=kind,
        org={"id": organization_id, "name": "Acme"},
        plugin={"identifier": identifier, "version": "0.2.0"},
        previous_version=None,
    )
    return encode_hook_body(request).decode("utf-8")


def hook_invocation(
    job_id: int = 41,
    organization_id: int = 3,
    *,
    attempt: int = 1,
    timeout_seconds: int = 30,
    identifier: str = "weather",
    kind: str = "install",
) -> dict:
    """A `HookInvocation` as django_app answers a claim."""
    return {
        "job_id": job_id,
        "kind": kind,
        "attempt": attempt,
        "organization_id": organization_id,
        "timeout_seconds": timeout_seconds,
        "assertion": HOOK_ASSERTION,
        "body": hook_body(job_id, organization_id, attempt, identifier, kind),
    }


def runtime_file_document(identifier: str = "weather", version: str = "0.2.0", **overrides) -> dict:
    signer = ContextSigner(plugin_identifier=identifier, plugin_version=version)
    return {
        "format": 1,
        "plugin": {"identifier": identifier, "version": version},
        "issuer": "https://epicstaff.example.com",
        "public_url": f"https://{identifier}.plugins.example.com",
        "epicstaff_public_url": "https://epicstaff.example.com",
        "epicstaff_api_url": API_URL,
        "settings": {"units": "metric"},
        "secret_settings": {"forecast_api_token": "secret-token-value"},
        "service_accounts": {},
        "jwks": signer.jwks.model_dump(mode="json"),
        "public_paths": [],
        **overrides,
    }


class FakeDjango:
    """django_app's node API, in memory, behind an `httpx.MockTransport`."""

    def __init__(self):
        self.desired: DesiredState | None = None
        self.packages: dict[int, bytes] = {}
        self.runtime_files: dict[int, dict] = {}
        self.credentials_revisions: dict[int, str] = {}
        self.settings_revisions: dict[int, int] = {}
        self.database_passwords: dict[int, str] = {}
        """placement id -> the app password its runtime credentials carry (for a database)."""
        self.reports: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.unavailable = False
        self.hook_invocations: dict[int, dict] = {}
        """job id -> what its claim answers; claimed once (popped), then the job answers 409."""
        self.hook_results: list[tuple[int, dict]] = []
        self.failing_result_posts = 0
        """Answer this many result posts with `failing_result_status` before taking one."""
        self.failing_result_status = 503
        self.on_claim: Callable[[int], None] | None = None
        self.advances: list[tuple[int, dict]] = []
        """(upgrade id, body) of every advance request, in order."""
        self.advance_status = 204
        self.on_advance: Callable[[int, dict], None] | None = None
        """Called for each granted advance, as django_app would move the desired state on."""
        self.transport = httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.unavailable:
            raise httpx.ConnectError("connection refused", request=request)
        if request.headers.get("Authorization") != f"PluginNodeKey {NODE_KEY}":
            return httpx.Response(401, json={"code": "node_not_authenticated"})
        path = request.url.path.removeprefix("/api/")
        parts = path.strip("/").split("/")
        if path == "plugin-nodes/self/desired-state/":
            etag = f'"{self.desired.revision}"'
            if request.headers.get("If-None-Match") == etag:
                return httpx.Response(304)
            return httpx.Response(
                200, content=self.desired.model_dump_json(), headers={"ETag": etag}
            )
        if parts[:3] == ["plugin-nodes", "self", "packages"]:
            package = self.packages.get(int(parts[3]))
            if package is None:
                return httpx.Response(404, json={"code": "plugin_package_not_found"})
            return httpx.Response(
                200, content=package, headers={"X-Package-Sha256": sha256_hex(package)}
            )
        if parts[:3] == ["plugin-nodes", "self", "placements"] and request.method == "POST":
            placement_id = int(parts[3])
            credentials = {
                "placement_id": placement_id,
                "credentials_revision": self.credentials_revisions.get(placement_id, "c" * 64),
                "settings_revision": self.settings_revisions.get(placement_id, 0),
                "runtime_file": self.runtime_files[placement_id],
            }
            if placement_id in self.database_passwords:
                credentials["database"] = {"app_password": self.database_passwords[placement_id]}
            return httpx.Response(200, json=credentials)
        if path == "plugin-nodes/self/reports/" and request.method == "POST":
            self.reports.append(json.loads(request.content))
            return httpx.Response(204)
        if parts[:3] == ["plugin-nodes", "self", "hook-jobs"] and request.method == "POST":
            return self._handle_hook_job(int(parts[3]), parts[4], request)
        if parts[:3] == ["plugin-nodes", "self", "upgrades"] and parts[4:] == ["advance"]:
            body = json.loads(request.content)
            self.advances.append((int(parts[3]), body))
            if self.advance_status != 204:
                return httpx.Response(self.advance_status, json={"code": "refused_by_the_test"})
            if self.on_advance is not None:
                self.on_advance(int(parts[3]), body)
            return httpx.Response(204)
        return httpx.Response(404)

    def _handle_hook_job(self, job_id: int, action: str, request: httpx.Request) -> httpx.Response:
        if action == "claim":
            if self.on_claim is not None:
                self.on_claim(job_id)
            invocation = self.hook_invocations.pop(job_id, None)
            if invocation is None:
                return httpx.Response(409, json={"code": "hook_job_not_claimable"})
            return httpx.Response(200, json=invocation, headers={"Cache-Control": "no-store"})
        if self.failing_result_posts:
            self.failing_result_posts -= 1
            return httpx.Response(self.failing_result_status, json={"code": "refused_by_the_test"})
        self.hook_results.append((job_id, json.loads(request.content)))
        return httpx.Response(204)

    def requests_to(self, action: str) -> list[int]:
        """The job ids of the hook-job requests for `action` (`claim` or `result`), in order."""
        return [
            int(request.url.path.split("/")[-3])
            for request in self.requests
            if request.url.path.startswith("/api/plugin-nodes/self/hook-jobs/")
            and request.url.path.endswith(f"/{action}/")
        ]


# Serves the health check on the inherited listening socket (fd in EPICSTAFF_PLUGIN_LISTEN_FD),
# as a real plugin does; it never binds a port, so it cannot clash with the agent's held socket.
# It answers hook calls too: it appends each to HOOK_RECORD (path, the X-EpicStaff-Hook and
# Content-Type headers, the body in base64), waits HOOK_DELAY seconds, then answers done. One
# thread per request, so the health check goes on during a slow hook. Its health check fails
# until HEALTHY_AFTER seconds after its start.
HEALTH_SERVER = """
import base64, http.server, json, os, signal, socket, sys, time
listener = socket.socket(fileno=int(os.environ["EPICSTAFF_PLUGIN_LISTEN_FD"]))
started = time.monotonic()
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        healthy = time.monotonic() - started >= float(os.environ.get("HEALTHY_AFTER", "0"))
        self.send_response(200 if self.path == "/_epicstaff/health" and healthy else 404)
        self.end_headers()
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        record = {
            "path": self.path,
            "hook": self.headers.get("X-EpicStaff-Hook"),
            "content_type": self.headers.get("Content-Type"),
            "body": base64.b64encode(body).decode(),
            "started": time.time(),
        }
        with open(os.environ["HOOK_RECORD"], "a") as hooks:
            hooks.write(json.dumps(record) + "\\n")
        time.sleep(float(os.environ.get("HOOK_DELAY", "0")))
        answer = b'{"status":"done"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(answer)))
        self.end_headers()
        self.wfile.write(answer)
    def log_message(self, *arguments):
        pass
server = http.server.ThreadingHTTPServer(("0.0.0.0", 0), Handler, bind_and_activate=False)
server.socket = listener
print("listening", flush=True)
if os.environ.get("IGNORE_SIGTERM"):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
else:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
server.serve_forever()
"""


def listening_socket(port: int) -> socket.socket:
    """A bound, listening TCP socket on `port`, as the agent holds for a placement."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("0.0.0.0", port))
    listener.listen(16)
    listener.set_inheritable(True)
    return listener


class FakeLauncher:
    """The launcher's operations as the agent sees them, without root.

    `spawn` runs a small HTTP server that answers the health check on the listening socket the
    agent passes in (as a real plugin serves on its inherited fd 3), and records the command.
    """

    def __init__(self):
        self.operations: list[tuple] = []
        self.runtime_files: dict[str, bytes] = {}
        self.spawned: list[dict] = []
        self._processes: dict[int, list[subprocess.Popen]] = {}
        self.refuse_spawn: str | None = None
        # A plugin that ignores SIGTERM, so only the SIGKILL after the grace period stops it.
        self.ignore_sigterm = False
        # How the plugin stand-in answers hooks and its health check (see HEALTH_SERVER).
        self.hook_record = Path(os.devnull)
        self.hook_delay = 0.0
        self.healthy_after = 0.0
        # Removals: the next ones that find the launcher unreachable, and a refusal for the rest.
        self.unavailable_removals = 0
        self.refuse_removal: str | None = None

    async def prepare_plugin(self, plugin, uid):
        self.operations.append(("prepare_plugin", plugin, uid))

    async def install_code(self, plugin, uid, version):
        self.operations.append(("install_code", plugin, uid, version))

    async def prune_code(self, plugin, uid, keep_version):
        self.operations.append(("prune_code", plugin, uid, keep_version))
        return []

    async def write_runtime_file(self, plugin, uid, content):
        self.operations.append(("write_runtime_file", plugin, uid))
        self.runtime_files[plugin] = content

    async def spawn(self, plugin, uid, argv, environment, nice, output_descriptor, listen_descriptor):
        from es_plugins.agent.launcher_client import LauncherError

        if self.refuse_spawn:
            raise LauncherError(self.refuse_spawn)
        os.set_inheritable(listen_descriptor, True)
        process = subprocess.Popen(
            [sys.executable, "-c", HEALTH_SERVER],
            env={
                "PORT": environment["PORT"],
                "PATH": os.environ.get("PATH", ""),
                "EPICSTAFF_PLUGIN_LISTEN_FD": str(listen_descriptor),
                "HOOK_RECORD": str(self.hook_record),
                "HOOK_DELAY": str(self.hook_delay),
                "HEALTHY_AFTER": str(self.healthy_after),
                **({"IGNORE_SIGTERM": "1"} if self.ignore_sigterm else {}),
            },
            stdout=output_descriptor,
            stderr=output_descriptor,
            pass_fds=(listen_descriptor,),
            start_new_session=True,
        )
        self._processes.setdefault(uid, []).append(process)
        self.spawned.append(
            {"plugin": plugin, "uid": uid, "argv": argv, "environment": environment, "nice": nice}
        )
        self.operations.append(("spawn", plugin, uid))
        return SpawnedProcess(pid=process.pid, pidfd=os.pidfd_open(process.pid))

    async def terminate_uid(self, uid):
        self.operations.append(("terminate_uid", uid))
        for process in self._processes.get(uid, []):
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)

    async def kill_uid(self, uid):
        self.operations.append(("kill_uid", uid))
        for process in self._processes.get(uid, []):
            if process.poll() is None:
                process.kill()
            process.wait()
        return []

    async def remove_plugin(self, plugin, uid, *, timeout_seconds):
        """Kill the UID's processes and record the request; refuse or fail when told to."""
        from es_plugins.agent.launcher_client import LauncherError, LauncherUnavailableError

        self.operations.append(("remove_plugin", plugin, uid))
        if self.unavailable_removals:
            self.unavailable_removals -= 1
            raise LauncherUnavailableError("cannot reach the launcher: Connection refused")
        if self.refuse_removal:
            raise LauncherError(self.refuse_removal)
        await self.kill_uid(uid)

    async def exit_status(self, pid):
        for processes in self._processes.values():
            for process in processes:
                if process.pid == pid:
                    return process.poll()
        return None

    def processes_of(self, uid) -> list[subprocess.Popen]:
        return list(self._processes.get(uid, []))

    def kill_running(self, uid, signal_number=signal.SIGKILL):
        """Make the plugin's process die on its own, as a crash would."""
        for process in self._processes.get(uid, []):
            if process.poll() is None:
                process.send_signal(signal_number)

    def stop_all(self):
        for processes in self._processes.values():
            for process in processes:
                if process.poll() is None:
                    process.kill()
                process.wait()


def free_port() -> int:
    return free_ports(1)[0]


def free_ports(count: int) -> list[int]:
    """`count` different ports nothing listens on now (held together while chosen, so distinct)."""
    probes = [socket.socket() for _ in range(count)]
    try:
        for probe in probes:
            probe.bind(("0.0.0.0", 0))
        return [probe.getsockname()[1] for probe in probes]
    finally:
        for probe in probes:
            probe.close()


class RecordingProvisioner:
    """The node's `DatabaseProvisioner` without a server: records each call, fails when told to.

    `events`, when given, gets `("provision", plugin)` at each call, next to the launcher's.
    """

    def __init__(self, events: list | None = None):
        self.calls: list[dict] = []
        self.failures: list[Exception] = []
        """Raised by the next calls, one each, first first."""
        self.ledger: tuple[LedgerEntry, ...] | None = None
        """The ledger to answer with instead of the migrations' own entries."""
        self._events = events

    async def ensure(self, plugin, desired, app_password, migrations):
        from es_plugins.database.provisioner import ProvisionedDatabase

        self.calls.append(
            {"plugin": plugin, "desired": desired, "app_password": app_password, "migrations": migrations}
        )
        if self._events is not None:
            self._events.append(("provision", plugin))
        if self.failures:
            raise self.failures.pop(0)
        applied = tuple(
            LedgerEntry(name=migration.name, sha256=migration.sha256)
            for migration in sorted(migrations, key=lambda migration: migration.name)
        )
        ledger = self.ledger if self.ledger is not None else applied
        return ProvisionedDatabase(
            created=len(self.calls) == 1, ledger=ledger, applied=len(applied), size_bytes=8192
        )


class RecordingDropper:
    """The node's `DatabaseDropper` without a server: records each drop, fails when told to."""

    def __init__(self, events: list | None = None):
        self.drops: list = []
        self.failures: list[Exception] = []
        """Raised by the next drops, one each, first first."""
        self.nothing_left = False
        """Answer as a drop finding nothing there does (a drop already done)."""
        self._events = events

    async def drop(self, desired):
        from es_plugins.database.drop_sequence import DroppedDatabase

        self.drops.append(desired)
        if self._events is not None:
            self._events.append(("drop", desired.database_name))
        if self.failures:
            raise self.failures.pop(0)
        if self.nothing_left:
            return DroppedDatabase(databases=0, roles=0)
        return DroppedDatabase(databases=1, roles=3)


class RecordingBackups:
    """The node's `BackupService` without a server: writes a small backup into the real store.

    `events`, when given, gets `("backup", reason)` at each call, next to the launcher's.
    """

    def __init__(self, store, events: list | None = None):
        self.requests: list = []
        self.failures: list[Exception] = []
        """Raised by the next backups, one each, first first."""
        self.started = None
        """Set while a backup runs, when `hold` is set: released by setting `hold`."""
        self.hold = None
        self._store = store
        self._events = events

    async def backup(self, request):
        import asyncio as _asyncio

        from es_plugins.database.backup_store import METADATA_FORMAT, BackupMetadata, StoredBackup
        from src.shared.models.plugin_nodes import backup_file_name

        self.requests.append(request)
        if self._events is not None:
            self._events.append(("backup", request.reason))
        if self.hold is not None:
            self.started.set()
            await self.hold.wait()
        if self.failures:
            raise self.failures.pop(0)
        created_at = datetime.now(UTC).replace(microsecond=0)
        name = backup_file_name(created_at, request.upgrade_id, request.reason)
        directory = self._store.directory(request.plugin)
        dump_path, descriptor = self._store.create_temporary(directory, name)
        content = b"PGDMP fake dump of " + request.database.database_name.encode()
        os.write(descriptor, content)
        os.close(descriptor)
        metadata = BackupMetadata(
            format=METADATA_FORMAT,
            plugin=request.plugin,
            installation_id=request.database.installation_id,
            database_name=request.database.database_name,
            upgrade_id=request.upgrade_id,
            reason=request.reason,
            version=request.version,
            restore_id=request.restore_id,
            created_at=created_at,
            size_bytes=len(content),
            sha256=sha256_hex(content),
            pg_dump_version="pg_dump (PostgreSQL) 17.11",
            server_version="17.11",
            database_settings=[],
            ledger=[],
        )
        metadata_path = self._store.write_metadata(directory, name, metadata)
        final = self._store.publish(directory, dump_path, metadata_path, name)
        await _asyncio.sleep(0)
        return StoredBackup(file_name=name, path=final, metadata=metadata)


class RecordingRestores:
    """The node's `RestoreService` without a server: walks the steps, takes the pre-restore backup."""

    def __init__(self, backups: RecordingBackups, events: list | None = None):
        self.calls: list[dict] = []
        self.failures: list[Exception] = []
        self._backups = backups
        self._events = events

    async def restore(self, plugin, database, restore, *, version, app_password, on_step):
        from es_plugins.database.backup_service import BackupRequest
        from es_plugins.database.provisioner import ProvisionedDatabase
        from es_plugins.database.restore_service import RestoreOutcome

        self.calls.append(
            {"plugin": plugin, "database": database, "restore": restore, "version": version,
             "app_password": app_password}
        )
        if self._events is not None:
            self._events.append(("restore", restore.restore_id))
        on_step("verify", None)
        on_step("backup", None)
        pre_restore = await self._backups.backup(
            BackupRequest(plugin=plugin, database=database, upgrade_id=restore.upgrade_id,
                          reason="pre_restore", version=version, restore_id=restore.restore_id)
        )
        for step in ("close", "recreate", "restore", "settings", "assert"):
            on_step(step, pre_restore)
            if self.failures and step == "restore":
                raise self.failures.pop(0)
        ledger = (LedgerEntry(name="001_places.sql", sha256="a" * 64),)
        return RestoreOutcome(
            pre_restore=pre_restore,
            provisioned=ProvisionedDatabase(created=False, ledger=ledger, applied=0, size_bytes=4096),
        )
