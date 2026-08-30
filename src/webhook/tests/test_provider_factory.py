import pytest
from src.shared.models import NgrokConfigData, LocalhostConfigData, BaseTunnelConfigData
from app.providers.provider_factory import get_provider, ProviderNotFoundException
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel
from app.providers.tunnels.localhost_tunnel import LocalhostTunnel
from app.core.settings import settings


def test_ngrok_config_returns_ngrok_tunnel():
    config = NgrokConfigData(
        name="prod", auth_token="tok", domain="my.ngrok.app", region="eu"
    )

    provider = get_provider(config)

    assert isinstance(provider, NgrokTunnel)


def test_ngrok_tunnel_gets_settings_port_and_host():
    config = NgrokConfigData(name="prod", auth_token="tok")

    provider = get_provider(config)

    assert provider._port == settings.NGROK_TARGET_PORT
    assert provider._host == settings.NGROK_TARGET_HOST


def test_ngrok_tunnel_passes_auth_token_and_domain():
    config = NgrokConfigData(
        name="prod", auth_token="secret-token", domain="my.ngrok.app"
    )

    provider = get_provider(config)

    assert provider._auth_token == "secret-token"
    assert provider._domain == "my.ngrok.app"


def test_localhost_config_returns_localhost_tunnel():
    config = LocalhostConfigData(name="local")

    provider = get_provider(config)

    assert isinstance(provider, LocalhostTunnel)


def test_localhost_tunnel_gets_settings_port_and_host():
    config = LocalhostConfigData(name="local")

    provider = get_provider(config)

    assert provider._port == settings.LOCALHOST_TARGET_PORT
    assert provider._host == settings.LOCALHOST_TARGET_HOST


def test_localhost_tunnel_passes_domain():
    config = LocalhostConfigData(name="local", domain="http://my-dev.local")

    provider = get_provider(config)

    assert provider._domain == "http://my-dev.local"


def test_localhost_tunnel_domain_none_by_default():
    config = LocalhostConfigData(name="local")

    provider = get_provider(config)

    assert provider._domain is None


def test_unknown_config_raises_provider_not_found():
    class UnknownConfig(BaseTunnelConfigData):
        pass

    config = UnknownConfig(name="unknown")

    with pytest.raises(ProviderNotFoundException):
        get_provider(config)
