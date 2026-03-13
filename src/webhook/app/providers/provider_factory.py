from src.shared.models import BaseTunnelConfigData, NgrokConfigData
from .base import AbstractTunnelProvider
from .ngrok_tunnel import NgrokTunnel
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
            port=settings.WEBHOOK_PORT,
            auth_token=config.auth_token,
            domain=config.domain,
            region=config.region,
            reconnect_timeout=settings.WEBHOOK_TUNNEL_RECONNECT_TIMEOUT,
        )
    else:
        raise ProviderNotFoundException(f"No tunnel provider for type {type(config)}")
