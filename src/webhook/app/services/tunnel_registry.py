import asyncio
from loguru import logger
from typing import Optional

from app.providers.tunnels.base import AbstractTunnelProvider
from app.providers.provider_factory import get_provider
from src.shared.models import BaseTunnelConfigData, WebhookConfigData


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


def _connection_fingerprint(config: BaseTunnelConfigData) -> dict:
    """Fields that identify the tunnel's OWN connection parameters (name,
    auth token, domain, region, ...) -- as opposed to the inbound-request
    auth strategy (`auth`), which can change without needing to restart the
    tunnel itself (see `needs_auth_update` below).
    """
    return config.model_dump(exclude={"auth"})


class UnregisteredWebhookPathError(Exception):
    """Raised when no tunnel config is registered for the requested path.
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
            needs_auth_update = False

            async with self._lock:
                if unique_id not in self._tunnel_pool:
                    needs_restart = True
                else:
                    tunnel, active_config = self._tunnel_pool[unique_id]

                    if _connection_fingerprint(active_config) != _connection_fingerprint(
                        expected_config
                    ):
                        logger.info(f"Config for {unique_id} changed. Restarting...")
                        needs_restart = True
                    elif active_config != expected_config:
                        self._tunnel_pool[unique_id] = (tunnel, expected_config)
                        needs_auth_update = True

            if needs_restart:
                try:
                    await self.register(expected_config)
                    logger.info(f"Successfully synced {unique_id}")
                except Exception as e:
                    logger.error(f"Error registering {unique_id}: {e}")
            elif needs_auth_update:
                logger.info(
                    f"Auth config for {unique_id} updated without tunnel restart."
                )

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

        if len(matches) == 1:
            return matches[0]

        if len(matches) > 1:
            matched_ids = [unique_id for unique_id, _ in matches]
            logger.error(
                f"Ambiguous webhook path '{requested_path}' matches multiple "
                f"registered configs: {matched_ids}"
            )
            raise AmbiguousWebhookPathError(
                path=requested_path, matched_ids=matched_ids
            )

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
