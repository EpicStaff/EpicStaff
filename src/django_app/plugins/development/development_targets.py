"""Development targets: the ports on the author's machine a plugin is served from.

Two fixed targets, the backend and the page; nothing else can be rerouted. A target is
deployment-wide and only a SuperAdmin sets it. It is inert while `PLUGINS_DEV_MODE` is off:
every reader asks `development_mode_on()` itself.

Writes lock the plugin row first, then its service accounts, then their keys (the order of
`plugins.lifecycle.lifecycle_locks` and of the key mints). Once a write commits, this
process's gateway snapshots and page decisions are dropped; other processes follow within
`SNAPSHOT_CACHE_SECONDS` and `PAGE_DECISION_CACHE_SECONDS`.
"""

import threading
import time
from dataclasses import dataclass
from datetime import datetime

from asgiref.sync import sync_to_async
from django.db import transaction

from plugins.activity.recorder import ActivityRecorder
from plugins.audit import log_development_target_cleared, log_development_target_set
from plugins.development.development_host import DevelopmentHost, development_host
from plugins.development.development_mode import (
    development_api_port,
    development_api_url,
    development_mode_on,
)
from plugins.exceptions import (
    InvalidDevelopmentPortsError,
    PluginDevelopmentModeOffError,
    PluginNotFoundError,
    PluginNotRunningError,
)
from plugins.gateway.gateway_service import (
    SPA_UPSTREAM_HEADER,
    GatewayDecision,
    releasing_connections,
    snapshot_cache,
)
from plugins.identity.internal_listener import holds_gateway_secret
from plugins.identity.service_account_keys import (
    ServiceAccountKeyService,
    development_keys_issued_at,
)
from plugins.lifecycle.lifecycle_locks import lock_existing_plugin, lock_plugin
from plugins.models import Plugin, PluginDevelopmentTarget, PluginPackage, PluginState
from plugins.models.development import development_target_of
from plugins.serializers.development import PluginDevelopmentUpdateSerializer

PAGE_DECISION_CACHE_SECONDS = 10
# Requests for many made-up plugin hosts must not grow one process's memory without bound.
MAX_CACHED_PAGE_DECISIONS = 1024


@dataclass(frozen=True)
class PluginDevelopmentState:
    """What a plugin's Development tab shows (`PluginDevelopmentSerializer`)."""

    development_mode: bool
    host: str
    host_address: str | None
    api_url: str | None
    can_use_backend: bool
    can_use_spa: bool
    target: PluginDevelopmentTarget | None
    runtime_file_issued_at: datetime | None


def routed_ports(plugin: Plugin) -> dict | None:
    """The stored ports while development mode is on, for the SuperAdmin; else None."""
    target = development_target_of(plugin) if development_mode_on() else None
    if target is None:
        return None
    return {"backend_port": target.backend_port, "spa_port": target.spa_port}


def served_from_development(plugin: Plugin) -> bool:
    """Whether development mode reroutes some part of the plugin now.

    True only while the mode is on and a stored port is one the current package can use: a
    backend port with a backend, a page port with a page. So a member's banner never claims
    a rerouting that does not happen, as after an upgrade that dropped the page.
    """
    target = development_target_of(plugin) if development_mode_on() else None
    if target is None or plugin.current_package is None:
        return False
    manifest = plugin.current_package.parsed_manifest
    return (target.backend_port is not None and manifest.backend is not None) or (
        target.spa_port is not None and manifest.spa is not None
    )


def clear_development_caches() -> None:
    """Drop this process's gateway snapshots and page decisions."""
    snapshot_cache.clear()
    page_decision_cache.clear()


class DevelopmentTargetService:
    def state_of(self, identifier: str) -> PluginDevelopmentState:
        """The plugin's Development tab.

        Raises:
            PluginNotFoundError: No such plugin.
        """
        plugin = (
            Plugin.objects.select_related("current_package", "development_target__updated_by")
            .defer("current_package__icon_bytes")
            .filter(identifier=identifier)
            .first()
        )
        if plugin is None:
            raise PluginNotFoundError()
        return _state(plugin, development_target_of(plugin))

    def set_ports(self, identifier: str, data, actor) -> PluginDevelopmentState:
        """Store where the plugin's backend and page are served from; issues no key.

        `data` is the request body (`PluginDevelopmentUpdateSerializer`), validated here, after
        the plugin is known to be running, so the answer is 404, then 409, then 400.

        Raises:
            PluginNotFoundError: No such plugin.
            PluginDevelopmentModeOffError: Development mode is off.
            PluginNotRunningError: The plugin is not running.
            InvalidDevelopmentPortsError: The ports are invalid for this plugin.
        """
        with transaction.atomic():
            plugin = lock_existing_plugin(identifier)
            if not development_mode_on():
                raise PluginDevelopmentModeOffError()
            if plugin.state != PluginState.RUNNING:
                raise PluginNotRunningError()
            backend, spa = _parts(plugin.current_package)
            body = PluginDevelopmentUpdateSerializer(
                data=data,
                context={
                    "api_port": development_api_port(),
                    "can_use_backend": backend,
                    "can_use_spa": spa,
                },
            )
            if not body.is_valid():
                raise InvalidDevelopmentPortsError(body.problems())
            ports = body.validated_data
            target = PluginDevelopmentTarget.objects.filter(plugin=plugin).first()
            changed = target is None or (target.backend_port, target.spa_port) != (
                ports["backend_port"],
                ports["spa_port"],
            )
            if target is None:
                target = PluginDevelopmentTarget(plugin=plugin)
            target.backend_port = ports["backend_port"]
            target.spa_port = ports["spa_port"]
            target.updated_by = actor
            target.save()
            if changed:
                ActivityRecorder().development_target_set(
                    actor, plugin.identifier, ports["backend_port"], ports["spa_port"]
                )
                transaction.on_commit(
                    lambda: log_development_target_set(
                        actor,
                        identifier=plugin.identifier,
                        backend_port=ports["backend_port"],
                        spa_port=ports["spa_port"],
                    )
                )
            transaction.on_commit(clear_development_caches)
        return _state(plugin, target)

    def clear(self, identifier: str, actor) -> None:
        """Stop development: delete the target and revoke the plugin's development keys.

        Allowed while the mode is off, since it only removes state. Clearing a plugin with
        neither is a no-op that records nothing.

        Raises:
            PluginNotFoundError: No such plugin.
        """
        with transaction.atomic():
            plugin = lock_plugin(identifier)
            if plugin is None:
                raise PluginNotFoundError()
            deleted, _ = PluginDevelopmentTarget.objects.filter(plugin=plugin).delete()
            revoked_keys = ServiceAccountKeyService().revoke_development_keys(plugin)
            if not deleted and not revoked_keys:
                return
            ActivityRecorder().development_target_cleared(actor, plugin.identifier, revoked_keys)
            transaction.on_commit(
                lambda: log_development_target_cleared(
                    actor, identifier=plugin.identifier, revoked_keys=revoked_keys
                )
            )
            transaction.on_commit(clear_development_caches)


@dataclass(frozen=True)
class _PageFacts:
    running: bool
    has_spa: bool
    spa_port: int | None


class _PageDecisionCache:
    """Each plugin's page facts, read at most once per `PAGE_DECISION_CACHE_SECONDS`."""

    def __init__(self):
        self._entries: dict[str, tuple[float, _PageFacts | None]] = {}
        self._lock = threading.Lock()

    def get(self, identifier: str) -> _PageFacts | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(identifier)
        if entry is not None and now - entry[0] <= PAGE_DECISION_CACHE_SECONDS:
            return entry[1]
        facts = _load_page_facts(identifier)
        with self._lock:
            if len(self._entries) >= MAX_CACHED_PAGE_DECISIONS:
                self._entries.clear()
            self._entries[identifier] = (now, facts)
        return facts

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


page_decision_cache = _PageDecisionCache()


def development_spa_port(identifier: str) -> int | None:
    """The port the plugin's page is served from now, or None for its published files.

    None while the mode is off, without a target or a page port, while the plugin is not
    running, and when its package has no page.
    """
    if not development_mode_on():
        return None
    facts = page_decision_cache.get(identifier)
    if facts is None or not facts.running or not facts.has_spa:
        return None
    return facts.spa_port


class DevelopmentPageDecisionService:
    """Decides, for nginx, whether a plugin's page comes from its published files or from a
    frontend development server.

    204: serve the published files. 403 with `X-Plugin-Spa-Upstream: <address>:<port>`: proxy
    to that server. 403 without it: a development server is set but its host does not
    resolve, and nginx answers that it cannot be reached. A bare 404 without the gateway
    secret. `decide_async` runs it in a worker thread, as the gateway check does;
    `in_request_thread=True` runs it in the calling thread, for tests.
    """

    def __init__(self, *, in_request_thread: bool = False):
        self._in_request_thread = in_request_thread

    async def decide_async(self, secret: str, identifier: str) -> GatewayDecision:
        if self._in_request_thread:
            return await sync_to_async(self.decide)(secret, identifier)
        return await sync_to_async(releasing_connections(self.decide), thread_sensitive=False)(
            secret, identifier
        )

    def decide(self, secret: str, identifier: str) -> GatewayDecision:
        if not holds_gateway_secret(secret):
            return GatewayDecision(status=404)
        spa_port = development_spa_port(identifier)
        if spa_port is None:
            return GatewayDecision(status=204)
        address = development_host.address()
        if address is None:
            return GatewayDecision(status=403)
        return GatewayDecision(status=403, headers={SPA_UPSTREAM_HEADER: f"{address}:{spa_port}"})


def _load_page_facts(identifier: str) -> _PageFacts | None:
    plugin = (
        Plugin.objects.select_related("current_package", "development_target")
        .defer("current_package__icon_bytes")
        .filter(identifier=identifier)
        .first()
    )
    if plugin is None:
        return None
    target = development_target_of(plugin)
    _backend, spa = _parts(plugin.current_package)
    return _PageFacts(
        running=plugin.state == PluginState.RUNNING,
        has_spa=spa,
        spa_port=target.spa_port if target is not None else None,
    )


def _parts(package: PluginPackage | None) -> tuple[bool, bool]:
    """Whether the package has a backend, and whether it has a page."""
    if package is None:
        return False, False
    manifest = package.parsed_manifest
    return manifest.backend is not None, manifest.spa is not None


def _state(plugin: Plugin, target: PluginDevelopmentTarget | None) -> PluginDevelopmentState:
    mode_on = development_mode_on()
    backend, spa = _parts(plugin.current_package)
    return PluginDevelopmentState(
        development_mode=mode_on,
        host=DevelopmentHost.NAME,
        host_address=development_host.address() if mode_on else None,
        api_url=development_api_url() if mode_on else None,
        can_use_backend=backend,
        can_use_spa=spa,
        target=target,
        runtime_file_issued_at=development_keys_issued_at(plugin),
    )
