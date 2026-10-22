"""The gateway decision nginx asks for before it forwards a request to a plugin's backend.

The answer is a status and headers only: 200 with the upstream and a signed context, 401 or
403 with `X-Plugin-Deny` naming the reason (nginx turns each into the client's response), or
a bare 404 when the caller does not hold the gateway secret. The checks run in a fixed
order, so an earlier refusal never reveals what a later check would say.

A path the manifest does not declare public needs a plugin login token. 401 `login` means the
token is not acceptable (missing, invalid, expired, or its user, password or grant no longer
holds): the SDK renews it once. 403 `forbidden` means the token is fine but the person may no
longer use the plugin: the SDK stops. A login token never reaches the plugin process.

Every request to a plugin's `/api/` waits for this check, so the view is asynchronous and the
decision runs in one worker thread: it never queues behind Django's one thread for
synchronous views. A plugin's static data (version, upstream, public paths) is kept in
the process for 10 s; whether it is in service and its process up is read fresh on every
check, in one query by primary key, so a plugin uninstalled, being deleted or deleted answers
`not_found` on every path at once, a stopped one is refused at once and a started one served
at once. A plugin stopped for an upgrade answers `maintenance` on every path, public ones
included; once it is back, a person of an organization whose upgrade hook has not finished
gets `maintenance` too, and one whose upgrade failed gets `unavailable`.

In plugin development mode, a plugin with a development backend port is forwarded to that port
on `host.docker.internal` instead of its node, as an address django_app resolves. Its
availability is then only that the plugin is running: the node's process health does not
count, because the author's process is not the node's. Every other step keeps its order and
meaning; an address that does not resolve answers `unavailable`.
"""

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from asgiref.sync import sync_to_async
from django.db import close_old_connections
from epicstaff_plugin.contracts.gateway_context import ContextOrganization, ContextUser
from epicstaff_plugin.contracts.manifest import PublicPath

from plugins.development.development_host import development_host
from plugins.development.development_mode import development_mode_on
from plugins.exceptions import SigningKeyMissingError
from plugins.gateway.context_builder import public_context, user_context
from plugins.gateway.path_policy import canonical_path, match_public_path
from plugins.gateway.person_cache import person_for
from plugins.gateway.public_rate_limiter import PublicRateLimiter
from plugins.identity.internal_listener import holds_gateway_secret
from plugins.identity.plugin_login_tokens import (
    PluginLoginTokenRejected,
    looks_like_plugin_login_token,
    verify_plugin_login_token,
)
from plugins.models import (
    GrantState,
    PlacementHealth,
    PlacementObservedState,
    Plugin,
    PluginPlacement,
    PluginState,
)
from plugins.models.development import development_target_of
from plugins.nodes.desired_state_builder import PLACED_PLUGIN_STATES
from plugins.origins import PluginOrigins

SNAPSHOT_CACHE_SECONDS = 10
# Requests for many made-up plugin hosts must not grow one process's memory without bound.
MAX_CACHED_SNAPSHOTS = 1024

DENY_HEADER = "X-Plugin-Deny"
UPSTREAM_HEADER = "X-Plugin-Upstream"
CONTEXT_HEADER = "X-Plugin-Context"
FORWARD_AUTHORIZATION_HEADER = "X-Plugin-Forward-Authorization"
# The page decision's answer in development mode: where the plugin's page is served from.
SPA_UPSTREAM_HEADER = "X-Plugin-Spa-Upstream"

DENY_FORBIDDEN = "forbidden"
DENY_LOGIN = "login"
DENY_MAINTENANCE = "maintenance"
DENY_NOT_FOUND = "not_found"
DENY_RATE_LIMITED = "rate_limited"
DENY_TOO_LARGE = "too_large"
DENY_UNAVAILABLE = "unavailable"
# A body may come without a length over HTTP/2 even when it is not chunked; on these
# methods the check cannot tell an empty body from an unbounded one.
BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# The plugin states the gateway answers for: in service, or stopped for an upgrade.
GATEWAY_PLUGIN_STATES = (*PLACED_PLUGIN_STATES, PluginState.MAINTENANCE)
# How a person of an organization whose grant is in these states is answered, once the token
# and the person hold.
_GRANT_STATE_DENIES = {
    GrantState.UPGRADING: DENY_MAINTENANCE,
    GrantState.UPGRADE_FAILED: DENY_UNAVAILABLE,
}


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
    authorization: str

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
            authorization=meta.get("HTTP_AUTHORIZATION", ""),
        )


@dataclass(frozen=True)
class GatewayDecision:
    status: int
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PluginSnapshot:
    """A plugin's static data, read once per `SNAPSHOT_CACHE_SECONDS`.

    `development_backend_port` is the stored development target's backend port, used only
    while development mode is on.
    """

    plugin_id: int
    identifier: str
    version: str
    upstream: str
    public_paths: tuple[PublicPath, ...]
    development_backend_port: int | None


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
        PluginPlacement.objects.select_related(
            "node", "plugin__current_package", "plugin__development_target"
        )
        .defer("plugin__current_package__icon_bytes")
        .filter(
            plugin__identifier=identifier,
            plugin__state__in=GATEWAY_PLUGIN_STATES,
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
    target = development_target_of(plugin)
    return PluginSnapshot(
        plugin_id=plugin.pk,
        identifier=plugin.identifier,
        version=manifest.version,
        upstream=f"{placement.node.internal_host}:{placement.port}",
        public_paths=tuple(manifest.public_paths),
        development_backend_port=target.backend_port if target is not None else None,
    )


def availability_refusal(plugin_id: int, *, development: bool = False) -> str | None:
    """Why the plugin's backend cannot be reached now, read fresh in one query; None when it
    is running and its process reported running and healthy.

    `not_found` once the plugin is out of service (uninstalled, being deleted, or deleted),
    so every path of it, public ones included, answers as an unknown plugin's would, from
    the moment the change commits; `maintenance` while it is stopped for an upgrade;
    `unavailable` while it is in service but not up. For a `development` backend, being up
    is only the plugin running: its node process does not serve the requests.
    """
    row = (
        Plugin.objects.filter(pk=plugin_id)
        .values_list("state", "placement__observed_state", "placement__health")
        .first()
    )
    if row is None or row[0] not in GATEWAY_PLUGIN_STATES:
        return DENY_NOT_FOUND
    if row[0] == PluginState.MAINTENANCE:
        return DENY_MAINTENANCE
    if development:
        return None if row[0] == PluginState.RUNNING else DENY_UNAVAILABLE
    if row != (PluginState.RUNNING, PlacementObservedState.RUNNING, PlacementHealth.OK):
        return DENY_UNAVAILABLE
    return None


def _route(snapshot: PluginSnapshot) -> tuple[str | None, str | None]:
    """The refusal, or the upstream: the development backend while development mode is on
    and a backend port is stored, else the node's process."""
    development_port = snapshot.development_backend_port if development_mode_on() else None
    if development_port is None:
        return availability_refusal(snapshot.plugin_id), snapshot.upstream
    refusal = availability_refusal(snapshot.plugin_id, development=True)
    if refusal is not None:
        return refusal, None
    address = development_host.address()
    if address is None:
        return DENY_UNAVAILABLE, None
    return None, f"{address}:{development_port}"


def _deny(status: int, reason: str) -> GatewayDecision:
    return GatewayDecision(status=status, headers={DENY_HEADER: reason})


class GatewayDecisionService:
    """Decides one gateway check. Paths outside public paths need a plugin login token.

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
        return await sync_to_async(releasing_connections(self.decide), thread_sensitive=False)(
            check
        )

    def decide(self, check: GatewayCheckRequest) -> GatewayDecision:
        if not holds_gateway_secret(check.secret):
            return GatewayDecision(status=404)
        snapshot = snapshot_cache.get(check.identifier)
        if snapshot is None:
            return _deny(403, DENY_NOT_FOUND)
        path = canonical_path(check.raw_uri, check.normalized_path)
        if path is None:
            return _deny(403, DENY_NOT_FOUND)
        refusal, upstream = _route(snapshot)
        if refusal is not None:
            return _deny(403, refusal)
        matched = match_public_path(list(snapshot.public_paths), check.method, path)
        if matched is None:
            return _logged_in_decision(check, snapshot, path, upstream)
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
        bearer = _bearer_token(check.authorization)
        # A public path's own Authorization (a plugin's API token, say) is the plugin's
        # business, so it is passed on; a plugin login token is EpicStaff's, and stays here.
        forward = bearer is None or not looks_like_plugin_login_token(bearer)
        return _forward(upstream, context, forward_authorization=forward)


def _logged_in_decision(
    check: GatewayCheckRequest, snapshot: PluginSnapshot, path: str, upstream: str
) -> GatewayDecision:
    """Decide a request to a path that is not public: it needs a valid plugin login token."""
    token = _bearer_token(check.authorization)
    if token is None:
        return _deny(401, DENY_LOGIN)
    try:
        claims = verify_plugin_login_token(token, snapshot.identifier)
    except PluginLoginTokenRejected:
        return _deny(401, DENY_LOGIN)
    person = person_for(claims)
    if not person.holds(claims):
        return _deny(401, DENY_LOGIN)
    # Before the organization's upgrade answer: someone no longer a member learns nothing
    # about that organization.
    if not person.member:
        return _deny(403, DENY_FORBIDDEN)
    if (refusal := _GRANT_STATE_DENIES.get(person.grant_state)) is not None:
        return _deny(403, refusal)
    if not person.grant_usable:
        return _deny(401, DENY_LOGIN)
    if not person.may_use:
        return _deny(403, DENY_FORBIDDEN)
    try:
        context = user_context(
            PluginOrigins().epicstaff_origin,
            snapshot.identifier,
            snapshot.version,
            check.method,
            path,
            organization=ContextOrganization(id=claims.org_id, name=person.organization_name),
            user=ContextUser(id=claims.user_id, email=person.email, name=person.name),
            permissions=person.actions,
        )
    except SigningKeyMissingError:
        return _deny(403, DENY_UNAVAILABLE)
    return _forward(upstream, context, forward_authorization=False)


def _forward(upstream: str, context: str, *, forward_authorization: bool) -> GatewayDecision:
    return GatewayDecision(
        status=200,
        headers={
            UPSTREAM_HEADER: upstream,
            CONTEXT_HEADER: context,
            FORWARD_AUTHORIZATION_HEADER: "1" if forward_authorization else "0",
        },
    )


def _bearer_token(authorization: str) -> str | None:
    """The token of `Authorization: Bearer <token>` (the scheme in any case), or None."""
    scheme, _, token = authorization.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token or any(character.isspace() for character in token):
        return None
    return token


def releasing_connections(function: Callable[..., Any]) -> Callable[..., Any]:
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


def _body_too_large(check: GatewayCheckRequest, rule: PublicPath) -> bool:
    if not check.content_length:
        # Without a length the body size is unknown until it streams, so a chunked body, or
        # one a body method may carry (HTTP/2 needs no length), is refused rather than checked.
        return "chunked" in check.transfer_encoding.lower() or check.method in BODY_METHODS
    if not check.content_length.isascii() or not check.content_length.isdigit():
        return True
    return int(check.content_length) > rule.max_body_kb * 1024
