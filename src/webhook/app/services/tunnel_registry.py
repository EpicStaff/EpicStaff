import asyncio
from loguru import logger
from typing import Optional

from app.providers.tunnels.base import AbstractTunnelProvider
from app.providers.provider_factory import get_provider
from src.shared.models import BaseTunnelConfigData, WebhookConfigData


class UnregisteredWebhookPathError(Exception):
    """Raised when no tunnel config is registered for the requested path.

    Routing is purely path-based (see `TunnelRegistry.resolve_by_path`) --
    the `path` is a cryptographically unguessable name, not a Host header, so
    it alone is the secure routing key. `domain` is kept as a constructor
    field for backward compatibility with older callers/log formatting, but
    is no longer a meaningful routing input; it is always passed as the
    literal `"N/A (Path Routing)"` placeholder.
    """

    def __init__(self, domain: str, path: str, registered_ids: list[str]):
        self.domain = domain
        self.path = path
        self.registered_ids = registered_ids
        super().__init__(
            f"No webhook registered for path '{path}' (domain: '{domain}'). "
            f"Registered paths: {registered_ids}"
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

    @staticmethod
    def _normalize_path(path: str | None) -> str:
        return (path or "").strip("/")

    async def resolve_by_path(self, path: str) -> tuple[str, BaseTunnelConfigData]:
        """Resolve the unique_id and config based purely on the requested path.

        This eliminates reliance on spoofable Host headers. The `path` is cryptographically
        unguessable (UUID/secret) and acts as the secure routing key.
        """
        requested_path = self._normalize_path(path)

        async with self._lock:
            for unique_id, (tunnel, config) in self._tunnel_pool.items():
                if self._normalize_path(config.name) == requested_path:
                    return unique_id, config

        raise UnregisteredWebhookPathError(
            domain="N/A (Path Routing)",
            path=requested_path,
            registered_ids=list(self._tunnel_pool.keys()),
        )


_tunnel_registry: Optional[TunnelRegistry] = None


def get_tunnel_registry(redis_service=None) -> TunnelRegistry:
    global _tunnel_registry
    if _tunnel_registry is None:
        _tunnel_registry = TunnelRegistry(redis_service=redis_service)
    return _tunnel_registry
