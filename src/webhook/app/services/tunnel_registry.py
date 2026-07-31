import asyncio
from loguru import logger
from typing import Optional

from app.providers.tunnels.base import AbstractTunnelProvider
from app.providers.provider_factory import get_provider
from src.shared.models import BaseTunnelConfigData, WebhookConfigData


class UnregisteredWebhookPathError(Exception):
    """Raised when a request's domain is served by this service but no tunnel is
    registered for the requested path.

    The domain is known, so the set of paths registered for it is known too:
    a request for any other path can never be processed by anything downstream,
    and must be rejected instead of being attributed to an unrelated config.
    """

    def __init__(self, domain: str, path: str, registered_ids: list[str]):
        self.domain = domain
        self.path = path
        self.registered_ids = registered_ids
        super().__init__(
            f"No webhook registered for path '{path}' on domain '{domain}'. "
            f"Registered on this domain: {registered_ids}"
        )


class TunnelRegistry:
    def __init__(self, redis_service=None):
        self._tunnel_pool: dict[
            str, tuple[AbstractTunnelProvider, BaseTunnelConfigData]
        ] = dict()
        self._lock = asyncio.Lock()
        self._redis_service = redis_service

    async def register(self, config: BaseTunnelConfigData):
        tunnel = get_provider(config)

        if self._redis_service:

            async def _on_url_set(url: str):
                await self._redis_service.set_tunnel_url(config.unique_id, url)

            tunnel._on_url_set = _on_url_set

        await tunnel.connect()

        async with self._lock:
            old_data = self._tunnel_pool.get(config.unique_id)
            self._tunnel_pool[config.unique_id] = (tunnel, config)

        if old_data:
            old_tunnel, _ = old_data
            logger.info(f"Replacing existing tunnel {config.unique_id}")
            try:
                await old_tunnel.disconnect()
            except Exception as e:
                logger.error(f"Error disconnecting old tunnel {config.unique_id}: {e}")

    async def unregister(self, unique_id: str):
        async with self._lock:
            if unique_id not in self._tunnel_pool:
                logger.warning(f"Tunnel {unique_id} not found in registry, skipping.")
                return
            tunnel, _ = self._tunnel_pool.pop(unique_id)

        try:
            await tunnel.disconnect()
        except Exception as e:
            logger.error(f"Error disconnecting from tunnel {unique_id}: {e}")

        if self._redis_service:
            try:
                await self._redis_service.delete_tunnel_url(unique_id)
            except Exception as e:
                logger.error(
                    f"Error deleting tunnel URL from Redis for {unique_id}: {e}"
                )

    async def register_many(self, webhook_config_data: WebhookConfigData):
        all_configs = [
            *webhook_config_data.ngrok_configs,
            *webhook_config_data.localhost_configs,
        ]
        expected_configs = {config.unique_id: config for config in all_configs}
        expected_ids = set(expected_configs.keys())

        async with self._lock:
            active_ids = set(self._tunnel_pool.keys())

        to_remove = active_ids - expected_ids
        for unique_id in to_remove:
            logger.info(f"Tunnel {unique_id} removed from DB. Shutting down...")
            await self.unregister(unique_id)

        for unique_id, expected_config in expected_configs.items():
            needs_restart = False

            async with self._lock:
                if unique_id not in self._tunnel_pool:
                    needs_restart = True
                else:
                    _, active_config = self._tunnel_pool[unique_id]

                    if active_config != expected_config:
                        logger.info(f"Config for {unique_id} changed. Restarting...")
                        needs_restart = True

            if needs_restart:
                try:
                    await self.register(expected_config)
                    logger.info(f"Successfully synced {unique_id}")
                except Exception as e:
                    logger.error(f"Error registering {unique_id}: {e}")

        async with self._lock:
            logger.debug(
                f"Current pool synced. Active tunnels: {list(self._tunnel_pool.keys())}"
            )

    async def get_tunnel(self, unique_id: str) -> AbstractTunnelProvider | None:
        async with self._lock:
            data = self._tunnel_pool.get(unique_id)
            return data[0] if data else None

    @staticmethod
    def _normalize_path(path: str | None) -> str:
        return (path or "").strip("/")

    async def resolve_unique_id(self, domain: str, path: str | None = None) -> str | None:
        """Resolve the `unique_id` of the tunnel an incoming request arrived through.

        A tunnel's public URL alone is NOT always a unique key: every localhost
        tunnel without an explicit `domain` gets the exact same
        `http://{host}:{port}` public URL (see `LocalhostTunnel._get_webhook_url`),
        so a domain-only match would return whichever localhost config happened
        to register first and every other localhost webhook would be attributed
        to the wrong config.

        So resolution is domain first, then `path` as the tie-breaker. A config's
        registered path is its `name` (`ConverterService` builds the config with
        `name=trigger.path`), which is also the segment embedded in `unique_id`
        (`"<provider>:<registered_path>"`).

        Returns `None` only when this service knows nothing about `domain`
        (empty Host, or a host that matches no active tunnel's public URL) —
        downstream then falls back to path-only trigger lookup, which keeps
        requests arriving through a proxy that rewrote Host working.

        Raises `UnregisteredWebhookPathError` when the domain IS known but no
        tunnel on it is registered for `path`: nothing downstream can process
        such a request, so the caller must reject it rather than hand back some
        other config's id.
        """
        if not domain:
            return None

        # NOTE: yeah, it's O(n), but N is almost always equals to 1 or 2
        async with self._lock:
            candidates = [
                (unique_id, config)
                for unique_id, (tunnel, config) in self._tunnel_pool.items()
                if tunnel._public_url and domain in tunnel._public_url
            ]

        if not candidates:
            return None

        # No path to match against (callers that only know the domain):
        # domain-only resolution, unambiguous for ngrok and a single localhost.
        if path is None:
            if len(candidates) == 1:
                return candidates[0][0]
            logger.warning(
                f"Ambiguous domain-only resolution for '{domain}'. "
                f"Candidates: {[unique_id for unique_id, _ in candidates]}"
            )
            return candidates[0][0]

        requested_path = self._normalize_path(path)
        for unique_id, config in candidates:
            if self._normalize_path(config.name) == requested_path:
                return unique_id

        # The domain is served here, so its registered paths are fully known and
        # `requested_path` is not one of them. Returning any candidate's id would
        # attribute the request to an unrelated webhook, and returning None would
        # make downstream fall back to path-only lookup — both let the caller
        # answer "success" for an event nothing will ever process.
        raise UnregisteredWebhookPathError(
            domain=domain,
            path=requested_path,
            registered_ids=[unique_id for unique_id, _ in candidates],
        )


_tunnel_registry: Optional[TunnelRegistry] = None


def get_tunnel_registry(redis_service=None) -> TunnelRegistry:
    global _tunnel_registry
    if _tunnel_registry is None:
        _tunnel_registry = TunnelRegistry(redis_service=redis_service)
    return _tunnel_registry
