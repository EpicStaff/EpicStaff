import asyncio

from fastapi import Request
from foundation.cryptographer import AbstractCryptographer, CryptographerError
from loguru import logger
from src.shared.models import BaseTunnelConfigData, WebhookConfigData

from app.providers.provider_factory import get_provider
from app.providers.tunnels.base import AbstractTunnelProvider


class AmbiguousWebhookPathError(Exception):
    """Raised when a requested path matches more than one registered tunnel
    config in the pool.
    """

    def __init__(self, path: str, matched_ids: list[str]):
        self.path = path
        self.matched_ids = matched_ids
        super().__init__(
            f"Path '{path}' matches multiple registered tunnel configs "
            f"{matched_ids} -- refusing to guess which one owns this request."
        )


def _opened(sealed: str, cryptographer: AbstractCryptographer) -> object:
    """Return the plaintext of a transport-sealed value, for comparison only.

    A value that cannot be decrypted becomes a fresh object equal only to itself, so it
    never compares equal and always counts as a change. Never log or store the result.
    """
    try:
        return cryptographer.decrypt(sealed)
    except CryptographerError:
        return object()


def _connection_fingerprint(
    config: BaseTunnelConfigData, cryptographer: AbstractCryptographer
) -> dict:
    """Fields that identify the tunnel's OWN connection parameters (name,
    auth token, domain, region, ...) -- as opposed to the inbound-request
    auth strategy (`auth`), which can change without needing to restart the
    tunnel itself (see `TunnelRegistry._apply_without_restarts`).

    A sealed `auth_token` is compared as plaintext: Django seals it afresh on every
    publish, so its ciphertext changes even when the token does not. An undecryptable
    token always counts as changed, so its config takes the restart path and its
    registration reports the failure.
    """
    fingerprint = config.model_dump(exclude={"auth"})
    if fingerprint.get("auth_token"):
        fingerprint["auth_token"] = _opened(fingerprint["auth_token"], cryptographer)
    return fingerprint


def _auth_fingerprint(
    config: BaseTunnelConfigData, cryptographer: AbstractCryptographer
) -> dict | None:
    """The inbound-request auth strategy, its secret compared as plaintext.

    Django reseals `auth.secret` on every publish, so comparing the configs as sent
    would report an auth change on every sync. An undecryptable secret always counts
    as changed.
    """
    if config.auth is None:
        return None
    fingerprint = config.auth.model_dump()
    if fingerprint.get("secret"):
        fingerprint["secret"] = _opened(fingerprint["secret"], cryptographer)
    return fingerprint


class UnregisteredWebhookPathError(Exception):
    """Raised when no tunnel config is registered for the requested path."""

    def __init__(self, domain: str, path: str, registered_ids: list[str]):
        self.domain = domain
        self.path = path
        self.registered_ids = registered_ids
        super().__init__(
            f"No webhook registered for path '{path}' (domain: '{domain}'). "
            f"Registered paths: {registered_ids}"
        )


class UnavailableWebhookPathError(Exception):
    """Raised when the requested path belongs to a config whose registration failed.

    The webhook exists in Django, so the sender should retry rather than drop the URL.
    """

    def __init__(self, path: str):
        self.path = path
        super().__init__(f"Webhook for path '{path}' failed to register and is not served.")


class ConfigsFailedToRegisterError(Exception):
    """Raised by `register_many` once it applied a config set except the configs named here.

    Every other config of the set was applied. The failed ones are not served until a
    later config set registers them.
    """

    def __init__(self, failed_ids: list[str]):
        self.failed_ids = failed_ids
        super().__init__(f"Tunnel configs failed to register: {failed_ids}")


class TunnelRegistry:
    """The tunnels serving Django's webhook configs, and how a request path resolves to one.

    Only the tunnel config listener's task mutates the pool (`register_many` and what it
    calls); request handlers only read it, and shutdown runs after the listener stopped.
    `unregister`, `register_many` and `_stop_serving` rely on that single writer: they
    release the lock before `_shut_down`, and `register` before `connect`, which is safe
    only because no other task can change the same id in between. `register` replaces
    whatever entry is pooled for the id when its tunnel has connected, including one
    `register_many` swapped the new config into for the duration of the restart.
    """

    def __init__(self, cryptographer: AbstractCryptographer, redis_service=None):
        """Create an empty registry.

        Args:
            cryptographer: Opens the transport-sealed secrets of the configs: the ngrok
                auth token a tunnel starts with, and the values the fingerprints compare.
        """
        self._tunnel_pool: dict[str, tuple[AbstractTunnelProvider, BaseTunnelConfigData]] = {}
        self._lock = asyncio.Lock()
        self._cryptographer = cryptographer
        self._redis_service = redis_service
        self._has_full_config_set = False
        # Normalized paths of the configs that failed to register: those of the last applied
        # set, plus those that failed so far in the set being applied.
        self._unavailable_paths: frozenset[str] = frozenset()
        # Consecutive failed registration attempts of each config that is failing now, so a
        # config failing on every sync logs one error, then a warning per sync with the
        # attempt count.
        self._failed_attempts: dict[str, int] = {}

    def has_full_config_set(self) -> bool:
        """Return whether a full config set from Django has been applied yet.

        Until then the registry is empty because nothing was synced, not because no
        webhook exists, so a missing path says nothing about the request.
        """
        return self._has_full_config_set

    async def register(self, config: BaseTunnelConfigData):
        tunnel = get_provider(config, self._cryptographer)

        if self._redis_service:

            async def _on_url_set(url: str):
                await self._redis_service.set_tunnel_url(config.unique_id, url)

            tunnel._on_url_set = _on_url_set

        try:
            await tunnel.connect()
        except asyncio.CancelledError:
            # The new tunnel is not in the pool yet, so nothing else would ever disconnect it.
            await asyncio.shield(tunnel.disconnect())
            raise

        async with self._lock:
            old_data = self._tunnel_pool.get(config.unique_id)
            self._tunnel_pool[config.unique_id] = (tunnel, config)

        if old_data:
            old_tunnel, _ = old_data
            logger.info(f"Replacing existing tunnel {config.unique_id}")
            try:
                # Shielded: the old tunnel has already left the pool, so a cancelled caller
                # must not leave it half disconnected.
                await asyncio.shield(old_tunnel.disconnect())
            except Exception as e:
                logger.error(f"Error disconnecting old tunnel {config.unique_id}: {e}")

    async def unregister(self, unique_id: str):
        async with self._lock:
            if unique_id not in self._tunnel_pool:
                logger.warning(f"Tunnel {unique_id} not found in registry, skipping.")
                return
            tunnel, _ = self._tunnel_pool.pop(unique_id)

        await self._shut_down(unique_id, tunnel)

    async def _shut_down(self, unique_id: str, tunnel: AbstractTunnelProvider) -> None:
        """Delete the URL of a tunnel already popped from the pool, then disconnect it."""
        # Before the disconnect: the tunnel is unroutable once popped, and a cancelled
        # disconnect (shutdown deadline) must not leave its URL behind.
        if self._redis_service:
            try:
                await self._redis_service.delete_tunnel_url(unique_id)
            except Exception as e:
                logger.error(f"Error deleting tunnel URL from Redis for {unique_id}: {e}")

        try:
            # Shielded for the same reason as the replaced tunnel in register().
            await asyncio.shield(tunnel.disconnect())
        except Exception as e:
            logger.error(f"Error disconnecting from tunnel {unique_id}: {e}")

    async def unregister_all(self) -> None:
        """Unregister every tunnel concurrently.

        One slow tunnel does not hold up the others; unregister() logs and swallows each
        tunnel's own errors.
        """
        async with self._lock:
            unique_ids = list(self._tunnel_pool)

        await asyncio.gather(*(self.unregister(unique_id) for unique_id in unique_ids))

    async def register_many(self, webhook_config_data: WebhookConfigData):
        """Replace the pool with Django's full config set.

        Tunnels missing from the set are unregistered, changed ones restarted, and an
        auth-only change is swapped in without a restart. Removals, auth changes and the
        new auth and path of every tunnel to restart take effect together, before the
        first (slow) tunnel start, so no request is checked against a superseded secret
        while tunnels start. A config whose (re)registration fails is unregistered too
        rather than left on a tunnel that did not restart; its path answers as unavailable
        until a later set registers it. One failure does not stop the rest of the set
        applying.

        A config's first failed attempt is logged as an error, its repeats as warnings
        with the attempt count.

        Raises:
            ConfigsFailedToRegisterError: Some configs failed to register; everything else
                of the set was applied.
        """
        all_configs = [
            *webhook_config_data.ngrok_configs,
            *webhook_config_data.localhost_configs,
        ]
        expected_configs = {config.unique_id: config for config in all_configs}

        removed, to_start = await self._apply_without_restarts(expected_configs)
        for unique_id, tunnel in removed:
            await self._shut_down(unique_id, tunnel)

        failed_attempts: dict[str, int] = {}
        for expected_config in to_start:
            unique_id = expected_config.unique_id
            try:
                await self.register(expected_config)
                logger.info("Successfully synced {}", unique_id)
            except Exception as e:
                attempt = self._failed_attempts.get(unique_id, 0) + 1
                failed_attempts[unique_id] = attempt
                self._log_failed_registration(unique_id, attempt, e)
                await self._stop_serving(unique_id, expected_config)

        async with self._lock:
            self._has_full_config_set = True
            # Replaced rather than kept growing: the path of a failed config that Django
            # has since deleted or renamed is no longer a webhook at all.
            self._unavailable_paths = frozenset(
                self._normalize_path(expected_configs[unique_id].name)
                for unique_id in failed_attempts
            )
            self._failed_attempts = failed_attempts
            logger.debug("Current pool synced. Active tunnels: {}", list(self._tunnel_pool.keys()))

        if failed_attempts:
            raise ConfigsFailedToRegisterError(list(failed_attempts))

    async def _apply_without_restarts(
        self, expected_configs: dict[str, BaseTunnelConfigData]
    ) -> tuple[list[tuple[str, AbstractTunnelProvider]], list[BaseTunnelConfigData]]:
        """Serve every config of the set from now on, except the tunnels still to start.

        Done in one lock acquisition, before any tunnel starts: starting one (pyngrok) can
        take tens of seconds, and until then requests must not be checked against a
        secret, or answered on a path, that the set has already replaced. So configs
        missing from the set leave the pool, an auth-only change is swapped in, and a
        config whose tunnel must restart is swapped into its running tunnel's pool entry.
        The running tunnel keeps forwarding requests meanwhile, which is safe because a
        request is matched by its path and checked against the auth of the config in the
        pool, now the new one. The path cannot differ: it is part of `unique_id`, so a
        renamed webhook is a removal, which stops its old path answering here and then,
        plus a new config. The restart replaces the tunnel, or `_stop_serving` drops the
        entry if it fails.

        Returns:
            The removed tunnels, still to shut down, and the configs whose tunnels must
            (re)start, in the set's order.
        """
        async with self._lock:
            removed = [
                (unique_id, self._tunnel_pool.pop(unique_id)[0])
                for unique_id in list(self._tunnel_pool)
                if unique_id not in expected_configs
            ]
            to_start: list[BaseTunnelConfigData] = []
            for unique_id, expected_config in expected_configs.items():
                pooled = self._tunnel_pool.get(unique_id)
                if pooled is None:
                    to_start.append(expected_config)
                    continue
                tunnel, active_config = pooled
                if _connection_fingerprint(
                    active_config, self._cryptographer
                ) != _connection_fingerprint(expected_config, self._cryptographer):
                    logger.info("Config for {} changed. Restarting...", unique_id)
                    self._tunnel_pool[unique_id] = (tunnel, expected_config)
                    to_start.append(expected_config)
                elif _auth_fingerprint(active_config, self._cryptographer) != _auth_fingerprint(
                    expected_config, self._cryptographer
                ):
                    self._tunnel_pool[unique_id] = (tunnel, expected_config)
                    logger.info("Auth config for {} updated without tunnel restart.", unique_id)
        for unique_id, _ in removed:
            logger.info("Tunnel {} removed from DB. Shutting down...", unique_id)
        return removed, to_start

    async def _stop_serving(self, unique_id: str, failed_config: BaseTunnelConfigData) -> None:
        """Fail closed on a config that failed to register.

        Its pool entry, if any, is the tunnel it was meant to replace, serving it until the
        restart finished; that tunnel runs with the superseded connection settings (a
        revoked ngrok token, say), so the entry leaves the pool. Its path turns unavailable
        in the same lock
        acquisition: the rest of the set may take seconds to register, and in between the
        path must answer as unavailable, not as unknown.
        """
        async with self._lock:
            superseded = self._tunnel_pool.pop(unique_id, None)
            self._unavailable_paths = self._unavailable_paths | {
                self._normalize_path(failed_config.name)
            }
        if superseded is not None:
            superseded_tunnel, _ = superseded
            await self._shut_down(unique_id, superseded_tunnel)

    @staticmethod
    def _log_failed_registration(unique_id: str, attempt: int, error: Exception) -> None:
        if attempt == 1:
            logger.error("Error registering {}: {}", unique_id, error)
        else:
            logger.warning(
                "Registering {} failed again (attempt {}): {}", unique_id, attempt, error
            )

    async def republish_tunnel_urls(self) -> None:
        """Write the public URL of every connected tunnel to Redis again.

        A tunnel writes its URL only when it connects, and `register_many` leaves an
        unchanged tunnel running, so URLs lost with a Redis restart stay lost until this
        runs.
        """
        if not self._redis_service:
            return
        async with self._lock:
            urls = {
                unique_id: tunnel.public_url
                for unique_id, (tunnel, _) in self._tunnel_pool.items()
                if tunnel.public_url
            }
        for unique_id, url in urls.items():
            await self._redis_service.set_tunnel_url(unique_id, url)

    @staticmethod
    def _normalize_path(path: str | None) -> str:
        return (path or "").strip("/")

    async def resolve_by_path(self, path: str) -> tuple[str, BaseTunnelConfigData]:
        """Resolve the unique_id and config based purely on the requested path.

        This eliminates reliance on spoofable Host headers. `path` is a
        user-chosen string (validated only by the permissive regex
        `^[a-zA-Z0-9]{1}[a-zA-Z0-9-_]*$` on the Django side), not a
        cryptographically unguessable secret. Cross-org collisions on it
        are now prevented structurally: Django's `WebhookTrigger` model
        enforces a DB-level uniqueness constraint on `path` alone (see the
        `unique=True` on `WebhookTrigger.path` and its accompanying
        migration), so two different orgs -- regardless of provider type
        -- can no longer register the same path at all. The
        `AmbiguousWebhookPathError` fallback below remains as defense-in-depth
        for this FastAPI service -- it should no longer be reachable via a
        legitimate cross-org registration attempt.

        `config.name` (the matching field) carries no org information --
        only `unique_id` does -- so two configs from different orgs (or
        different providers) can legitimately share the same `name`. When
        more than one pool entry matches, there is nothing in the request to
        disambiguate with, so this fails closed via
        `AmbiguousWebhookPathError` instead of returning an arbitrary match.
        """
        requested_path = self._normalize_path(path)

        async with self._lock:
            matches = [
                (unique_id, config)
                for unique_id, (tunnel, config) in self._tunnel_pool.items()
                if self._normalize_path(config.name) == requested_path
            ]
            is_unavailable = requested_path in self._unavailable_paths

        if not matches and is_unavailable:
            raise UnavailableWebhookPathError(path=requested_path)

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            matched_ids = [unique_id for unique_id, _ in matches]
            logger.error(
                f"Ambiguous webhook path '{requested_path}' matches multiple "
                f"registered configs: {matched_ids}"
            )
            raise AmbiguousWebhookPathError(path=requested_path, matched_ids=matched_ids)

        raise UnregisteredWebhookPathError(
            domain="N/A (Path Routing)",
            path=requested_path,
            registered_ids=list(self._tunnel_pool.keys()),
        )


def get_tunnel_registry(request: Request) -> TunnelRegistry:
    """Return the registry the app created on startup."""
    return request.app.state.tunnel_registry
