from .base import AbstractTunnelProvider
from .ngrok_tunnel import NgrokTunnel
from typing import Optional, Dict, Type

# --- Provider Registry ---
# To add a new provider (e.g., Cloudflare):
# 1. Create `cloudflare_tunnel.py` implementing `AbstractTunnelProvider`
# 2. Import it here: `from .cloudflare_tunnel import CloudflareTunnel`
# 3. Add to dict: `"cloudflare": CloudflareTunnel`
PROVIDERS: Dict[str, Type[AbstractTunnelProvider]] = {
    "ngrok": NgrokTunnel
}

class ProviderNotFoundException(ValueError):
    """Raised when the requested tunnel provider is not in the registry."""
    pass

def get_provider(
    provider_name: Optional[str], 
    port: int, 
    auth_token: Optional[str]
) -> AbstractTunnelProvider:
    """
    Factory function to get an instance of a tunnel provider.
    """
    if not provider_name:
        raise ProviderNotFoundException("No tunnel provider name was specified.")
    
    cleared_provider = provider_name.strip().lower()

    if cleared_provider not in PROVIDERS:
        raise ProviderNotFoundException(
            f"Provider '{cleared_provider}' not found. "
            f"Available providers: {list(PROVIDERS.keys())}"
        )
    
    # Get the class from the registry
    ProviderClass = PROVIDERS[cleared_provider]
    
    # Return an *instance* of the class
    return ProviderClass(port=port, auth_token=auth_token)
