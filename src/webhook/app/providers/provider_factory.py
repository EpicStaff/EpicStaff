from src.shared.models import BaseTunnelConfigData, NgrokConfigData, LocalhostConfigData
from .tunnels.base import AbstractTunnelProvider
from .tunnels.ngrok_tunnel import NgrokTunnel
from .tunnels.localhost_tunnel import LocalhostTunnel
from app.core.settings import settings


class ProviderNotFoundException(ValueError):
    """Raised when the requested tunnel provider is not in the registry."""

    pass


def get_provider(config: BaseTunnelConfigData) -> AbstractTunnelProvider:
    """
    Factory function to get an instance of a tunnel provider.
    """
    if isinstance(config, NgrokConfigData):
        return NgrokTunnel(
            port=settings.NGROK_TARGET_PORT,
            host=settings.NGROK_TARGET_HOST,
            auth_token=config.auth_token,
            domain=config.domain,
            region=config.region,
            reconnect_timeout=settings.WEBHOOK_TUNNEL_RECONNECT_TIMEOUT,
        )
    elif isinstance(config, LocalhostConfigData):
        return LocalhostTunnel(
            port=settings.LOCALHOST_TARGET_PORT,
            host=settings.LOCALHOST_TARGET_HOST,
            domain=config.domain,
        )
    else:
        raise ProviderNotFoundException(f"No tunnel provider for type {type(config)}")
