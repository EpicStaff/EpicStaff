import os
import shutil
import tempfile
import asyncio
from loguru import logger
from pyngrok import ngrok, installer, conf
from pyngrok.conf import PyngrokConfig
import pyngrok.process
from app.providers.base import AbstractTunnelProvider
from typing import Optional


class NgrokTunnel(AbstractTunnelProvider):
    def __init__(
        self,
        port: int,
        auth_token: Optional[str] = None,
        domain: Optional[str] = None,
        region: Optional[str] = None,
        reconnect_timeout: int = 10,
    ):
        super().__init__(port, auth_token, domain=domain)
        self._tunnel = None
        self._region = region
        self._reconnect_timeout = reconnect_timeout

        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

        if not self._auth_token:
            raise ValueError("NgrokTunnel requires an auth_token.")

        self._config_path = os.path.join(
            tempfile.gettempdir(), f"ngrok_config_{id(self)}.yml"
        )

        self._ngrok_path = os.path.join(tempfile.gettempdir(), f"ngrok_bin_{id(self)}")
        self._config = None

    async def connect(self):
        self._is_running = True
        await self._establish_connection()
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_connection())

    async def _establish_connection(self):
        async with self._lock:
            if not self._is_running or self._tunnel is not None:
                return

        print(
            f"Attempting to connect ngrok tunnel on port {self._port} "
            f"(Region: {self._region or 'eu'})..."
        )

        # Prefer the APT-installed system ngrok binary to avoid a runtime download
        # from equinox.io (which can fail).  pyngrok also installs its own Python
        # shim at /usr/local/bin/ngrok, so shutil.which() is not reliable here —
        # it finds the shim first.  Check known system binary paths explicitly.
        _SYSTEM_NGROK_CANDIDATES = ["/usr/local/bin/ngrok", "/usr/bin/ngrok"]
        system_ngrok = next(
            (
                p
                for p in _SYSTEM_NGROK_CANDIDATES
                if os.path.isfile(p) and os.access(p, os.X_OK)
            ),
            None,
        )
        if system_ngrok:
            resolved_ngrok_path = system_ngrok
        else:
            default_conf = conf.get_default()
            if not os.path.exists(default_conf.ngrok_path):
                installer.install_ngrok(default_conf.ngrok_path)
            resolved_ngrok_path = default_conf.ngrok_path

        if not os.path.exists(self._ngrok_path):
            try:
                os.symlink(resolved_ngrok_path, self._ngrok_path)
            except OSError:
                shutil.copy2(resolved_ngrok_path, self._ngrok_path)

        self._config = PyngrokConfig(
            auth_token=self._auth_token,
            region=self._region if self._region else "eu",
            config_path=self._config_path,
            ngrok_path=self._ngrok_path,
        )

        def _start():
            return ngrok.connect(
                self._port, "http", domain=self._domain, pyngrok_config=self._config
            )

        try:
            new_tunnel = await asyncio.to_thread(_start)

            async with self._lock:
                if not self._is_running:
                    print(
                        "Disconnect called during connection! Rolling back new tunnel..."
                    )

                    def _rollback():
                        ngrok.disconnect(
                            new_tunnel.public_url, pyngrok_config=self._config
                        )
                        pyngrok.process.kill_process(self._config.ngrok_path)

                    await asyncio.to_thread(_rollback)
                    return

                self._tunnel = new_tunnel
                self._public_url = self._tunnel.public_url
                print(f"Tunnel established: {self._public_url}")

            if self._public_url and self._on_url_set:
                await self._on_url_set(self._public_url)

        except Exception as e:
            logger.error(f"Failed to establish ngrok connection: {e}")
            raise

    async def _monitor_connection(self):
        try:
            while self._is_running:
                await asyncio.sleep(self._reconnect_timeout)
                if not self._is_running:
                    break
                async with self._lock:
                    needs_reconnect = self._tunnel is None
                if needs_reconnect:
                    try:
                        await self._establish_connection()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        logger.warning(
                            f"Reconnection attempt failed: {e}. "
                            f"Next try in {self._reconnect_timeout}s"
                        )
        except asyncio.CancelledError:
            logger.debug("Monitor task received cancellation.")
            raise
        finally:
            self._is_running = False

    async def disconnect(self):
        print(f"Disconnecting ngrok tunnel on port {self._port}...")
        self._is_running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await asyncio.wait_for(self._monitor_task, timeout=1.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._monitor_task = None

        async with self._lock:
            if self._tunnel and self._config:
                url_to_disconnect = self._tunnel.public_url

                def _close():
                    try:
                        ngrok.disconnect(url_to_disconnect, pyngrok_config=self._config)
                    except Exception as e:
                        logger.debug(f"Disconnect warning: {e}")

                    pyngrok.process.kill_process(self._config.ngrok_path)

                    for path_to_remove in [self._config_path, self._ngrok_path]:
                        if os.path.exists(path_to_remove):
                            try:
                                os.remove(path_to_remove)
                            except OSError:
                                pass

                try:
                    await asyncio.to_thread(_close)
                    logger.info(
                        f"Ngrok tunnel {url_to_disconnect} closed successfully."
                    )
                except Exception:
                    logger.exception(f"Failed to disconnect tunnel {url_to_disconnect}")
                finally:
                    self._tunnel = None
                    self._public_url = None
