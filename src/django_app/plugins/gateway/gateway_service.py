"""The gateway decision nginx asks for before it forwards a request to a plugin's backend.

The answer is a status and headers only: 200 with the upstream and a signed context, 401 or
403 with `X-Plugin-Deny` naming the reason (nginx turns each into the client's response), or
a bare 404 when the caller does not hold the gateway secret. The checks run in a fixed
order, so an earlier refusal never reveals what a later check would say.

Every request to a plugin's `/api/` waits for this check, so the view is asynchronous and the
decision runs in one worker thread: it never queues behind Django's one thread for
synchronous views. A plugin's static data (version, upstream, public paths) is kept in
the process for 10 s; whether its process is up is read fresh on every check, in one query
by primary key, so a stopped plugin is refused at once and a started one served at once.
"""

import hmac
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from asgiref.sync import sync_to_async
from django.conf import settings
from django.db import close_old_connections
from epicstaff_plugin.contracts.manifest import PublicPath

from plugins.exceptions import SigningKeyMissingError
from plugins.gateway.context_builder import public_context
from plugins.gateway.path_policy import canonical_path, match_public_path
from plugins.gateway.public_rate_limiter import PublicRateLimiter
from plugins.models import (
    PlacementHealth,
    PlacementObservedState,
    Plugin,
    PluginPlacement,
    PluginState,
)
from plugins.nodes.desired_state_builder import PLACED_PLUGIN_STATES
from plugins.origins import PluginOrigins

UNCONFIGURED_SECRET = "none"
SNAPSHOT_CACHE_SECONDS = 10
# Requests for many made-up plugin hosts must not grow one process's memory without bound.
MAX_CACHED_SNAPSHOTS = 1024

DENY_HEADER = "X-Plugin-Deny"
UPSTREAM_HEADER = "X-Plugin-Upstream"
CONTEXT_HEADER = "X-Plugin-Context"
FORWARD_AUTHORIZATION_HEADER = "X-Plugin-Forward-Authorization"

DENY_LOGIN = "login"
DENY_NOT_FOUND = "not_found"
DENY_RATE_LIMITED = "rate_limited"
DENY_TOO_LARGE = "too_large"
DENY_UNAVAILABLE = "unavailable"
# A body may come without a length over HTTP/2 even when it is not chunked; on these
# methods the check cannot tell an empty body from an unbounded one.
BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


@dataclass(frozen=True)
class GatewayCheckRequest:
    """What nginx tells the check about the original request (its explicit header list)."""

    secret: str
    identifier: str
    method: str
    raw_uri: str
    normalized_path: str
    content_length: str
    transfer_encoding: str
    client_address: str

    @classmethod
    def from_meta(cls, meta) -> "GatewayCheckRequest":
        return cls(
            secret=meta.get("HTTP_X_PLUGIN_GATEWAY_SECRET", ""),
            identifier=meta.get("HTTP_X_PLUGIN_IDENTIFIER", ""),
            method=meta.get("HTTP_X_ORIGINAL_METHOD", ""),
            raw_uri=meta.get("HTTP_X_ORIGINAL_URI", ""),
            normalized_path=meta.get("HTTP_X_ORIGINAL_NORMALIZED_PATH", ""),
            content_length=meta.get("HTTP_X_ORIGINAL_CONTENT_LENGTH", "").strip(),
            transfer_encoding=meta.get("HTTP_X_ORIGINAL_TRANSFER_ENCODING", "").strip(),
            client_address=meta.get("HTTP_X_REAL_IP", "").strip(),
        )


@dataclass(frozen=True)
class GatewayDecision:
    status: int
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginSnapshot:
    """A plugin's static data, read once per `SNAPSHOT_CACHE_SECONDS`."""

    plugin_id: int
    identifier: str
    version: str
    upstream: str
    public_paths: tuple[PublicPath, ...]


class _SnapshotCache:
    def __init__(self):
        self._entries: dict[str, tuple[float, PluginSnapshot | None]] = {}
        self._lock = threading.Lock()

    def get(self, identifier: str) -> PluginSnapshot | None:
        now = time.monotonic()
        with self._lock:
            entry = self._entries.get(identifier)
        if entry is not None and now - entry[0] <= SNAPSHOT_CACHE_SECONDS:
            return entry[1]
        snapshot = _load_snapshot(identifier)
        with self._lock:
            if len(self._entries) >= MAX_CACHED_SNAPSHOTS:
                self._entries.clear()
            self._entries[identifier] = (now, snapshot)
        return snapshot

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


snapshot_cache = _SnapshotCache()


def _load_snapshot(identifier: str) -> PluginSnapshot | None:
    """The plugin's snapshot, or None when it has no backend placed on a node."""
    placement = (
        PluginPlacement.objects.select_related("node", "plugin__current_package")
        .defer("plugin__current_package__icon_bytes")
        .filter(
            plugin__identifier=identifier,
            plugin__state__in=PLACED_PLUGIN_STATES,
            plugin__current_package__isnull=False,
        )
        .first()
    )
    if placement is None:
        return None
    plugin = placement.plugin
    manifest = plugin.current_package.parsed_manifest
    if manifest.backend is None:
        return None
    return PluginSnapshot(
        plugin_id=plugin.pk,
        identifier=plugin.identifier,
        version=manifest.version,
        upstream=f"{placement.node.internal_host}:{placement.port}",
        public_paths=tuple(manifest.public_paths),
    )


def is_available(plugin_id: int) -> bool:
    """Whether the plugin is running and its process reported running and healthy, read now."""
    row = (
        Plugin.objects.filter(pk=plugin_id)
        .values_list("state", "placement__observed_state", "placement__health")
        .first()
    )
    return row == (PluginState.RUNNING, PlacementObservedState.RUNNING, PlacementHealth.OK)


def _deny(status: int, reason: str) -> GatewayDecision:
    return GatewayDecision(status=status, headers={DENY_HEADER: reason})


class GatewayDecisionService:
    """Decides one gateway check. Paths outside public paths need a login once people can
    log in to plugins; until then they are refused.

    `decide_async` runs the whole decision in one worker thread, off the event loop.
    `in_request_thread=True` runs it in the calling thread instead, for tests whose
    database transaction other threads cannot see.
    """

    def __init__(
        self, rate_limiter: PublicRateLimiter | None = None, *, in_request_thread: bool = False
    ):
        self._rate_limiter = rate_limiter or PublicRateLimiter()
        self._in_request_thread = in_request_thread

    async def decide_async(self, check: GatewayCheckRequest) -> GatewayDecision:
        if self._in_request_thread:
            return await sync_to_async(self.decide)(check)
        return await sync_to_async(_releasing_connections(self.decide), thread_sensitive=False)(
            check
        )

    def decide(self, check: GatewayCheckRequest) -> GatewayDecision:
        if not _holds_gateway_secret(check.secret):
            return GatewayDecision(status=404)
        snapshot = snapshot_cache.get(check.identifier)
        if snapshot is None:
            return _deny(403, DENY_NOT_FOUND)
        path = canonical_path(check.raw_uri, check.normalized_path)
        if path is None:
            return _deny(403, DENY_NOT_FOUND)
        if not is_available(snapshot.plugin_id):
            return _deny(403, DENY_UNAVAILABLE)
        matched = match_public_path(list(snapshot.public_paths), check.method, path)
        if matched is None:
            return _deny(401, DENY_LOGIN)
        rule_index, rule = matched
        if _body_too_large(check, rule):
            return _deny(403, DENY_TOO_LARGE)
        if not self._rate_limiter.allow(
            snapshot.identifier, rule_index, check.client_address, rule.rate_limit_per_minute
        ):
            return _deny(403, DENY_RATE_LIMITED)
        try:
            context = public_context(
                PluginOrigins().epicstaff_origin,
                snapshot.identifier,
                snapshot.version,
                check.method,
                path,
            )
        except SigningKeyMissingError:
            return _deny(403, DENY_UNAVAILABLE)
        return GatewayDecision(
            status=200,
            headers={
                UPSTREAM_HEADER: snapshot.upstream,
                CONTEXT_HEADER: context,
                # A public path's own Authorization (a plugin's API token, say) is the
                # plugin's business, so it is passed on.
                FORWARD_AUTHORIZATION_HEADER: "1",
            },
        )


def _releasing_connections(function: Callable[..., Any]) -> Callable[..., Any]:
    """Run `function`, then give the worker thread's database connection back to the pool.

    Worker threads outlive the request, and Django closes connections only at the end of a
    request in its own thread; without this each worker would keep a pooled connection.
    """

    def run(*args: Any) -> Any:
        try:
            return function(*args)
        finally:
            close_old_connections()

    return run


def _holds_gateway_secret(presented: str) -> bool:
    configured = settings.PLUGINS_GATEWAY_SECRET or ""
    if configured in ("", UNCONFIGURED_SECRET):
        return False
    return hmac.compare_digest(presented.encode("utf-8"), configured.encode("utf-8"))


def _body_too_large(check: GatewayCheckRequest, rule: PublicPath) -> bool:
    if not check.content_length:
        # Without a length the body size is unknown until it streams, so a chunked body, or
        # one a body method may carry (HTTP/2 needs no length), is refused rather than checked.
        return "chunked" in check.transfer_encoding.lower() or check.method in BODY_METHODS
    if not check.content_length.isascii() or not check.content_length.isdigit():
        return True
    return int(check.content_length) > rule.max_body_kb * 1024
