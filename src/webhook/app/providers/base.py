import abc
from typing import Optional

class AbstractTunnelProvider(abc.ABC):
    """
    Defines the "contract" for any tunnel provider.
    """
    def __init__(self, port: int, auth_token: Optional[str] = None):
        """
        Initialize the provider with the port and an optional auth token.
        """
        self._port = port
        self._auth_token = auth_token
        self._public_url: Optional[str] = None

    @abc.abstractmethod
    async def connect(self):
        """Connect the tunnel and set the public URL."""
        raise NotImplementedError

    @abc.abstractmethod
    async def disconnect(self):
        """Disconnect the tunnel."""
        raise NotImplementedError

    @property
    def public_url(self) -> Optional[str]:
        return self._public_url
