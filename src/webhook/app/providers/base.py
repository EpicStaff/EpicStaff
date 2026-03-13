import abc
from typing import Awaitable, Callable, Optional


class AbstractTunnelProvider(abc.ABC):
    """
    Defines the "contract" for any tunnel provider (Ngrok, Cloudflare, SSH, etc.).
    """

    def __init__(
        self, port: int, auth_token: Optional[str] = None, domain: Optional[str] = None
    ):
        """
        Initialize the provider with the target port and optional credentials.
        """
        self._port = port
        self._auth_token = auth_token
        self._domain = domain
        self._public_url: Optional[str] = None
        self._on_url_set: Optional[Callable[[str], Awaitable[None]]] = None

        # New common state flag
        self._is_running: bool = False

    @abc.abstractmethod
    async def connect(self):
        """
        Entry point to start the tunnel service.
        Implementation should set self._is_running to True.
        """
        raise NotImplementedError

    @abc.abstractmethod
    async def disconnect(self):
        """
        Shutdown the tunnel service.
        Implementation should set self._is_running to False.
        """
        raise NotImplementedError

    @property
    def public_url(self) -> Optional[str]:
        """
        Return the current public URL of the tunnel.
        """
        return self._public_url

    @property
    def is_active(self) -> bool:
        """
        Check if the tunnel provider is supposed to be running.
        Note: This reflects the intended state, not necessarily the network health.
        """
        return self._is_running

    @property
    def is_connected(self) -> bool:
        """
        Check if the tunnel is physically established (has a public URL).
        """
        return self._public_url is not None
