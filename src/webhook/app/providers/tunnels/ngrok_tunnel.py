import asyncio
import contextlib
import os
import shutil
import stat
import tempfile

import pyngrok.process
from loguru import logger
from pyngrok import conf, installer, ngrok
from pyngrok.conf import PyngrokConfig

from app.providers.tunnels.base import AbstractTunnelProvider

# Headroom on top of pyngrok's own startup and request timeouts when disconnect() waits
# for an in-flight start.
START_WAIT_SLACK_SECONDS = 2


class NgrokWorkingDirectoryError(RuntimeError):
    """Raised when the private ngrok working directory or the binary in it is unusable."""


class NgrokTunnel(AbstractTunnelProvider):
    def __init__(
        self,
        port: int,
        host: str = "localhost",
        auth_token: str | None = None,
        domain: str | None = None,
        region: str | None = None,
        reconnect_timeout: int = 10,
    ):
        super().__init__(port, auth_token, domain=domain)
        self._host = host
        self._tunnel = None
        self._region = region
        self._reconnect_timeout = reconnect_timeout

        self._is_running = False
        self._monitor_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

        if not self._auth_token:
            raise ValueError("NgrokTunnel requires an auth_token.")

        # Private per-instance directory holding the ngrok config and binary. The binary
        # path must stay unique per instance: pyngrok keys its process registry by it.
        self._working_directory: str | None = None
        self._binary_placed = False
        self._config = None
        self._start_task: asyncio.Task | None = None

    async def connect(self):
        self._is_running = True
        if self._monitor_task is None or self._monitor_task.done():
            self._monitor_task = asyncio.create_task(self._monitor_connection())
        try:
            await self._establish_connection()
        except Exception as e:
            logger.warning(
                "Initial ngrok connection failed on port {}, monitor will retry in {}s: {}",
                self._port,
                self._reconnect_timeout,
                e,
            )

    async def _establish_connection(self):
        async with self._lock:
            if not self._is_running or self._tunnel is not None or self._start_task is not None:
                return

        logger.info(
            "Attempting to connect ngrok tunnel on port {} (Region: {})...",
            self._port,
            self._region or "eu",
        )

        # Prefer the APT-installed system ngrok binary to avoid a runtime download
        # from equinox.io (which can fail).  pyngrok also installs its own Python
        # shim at /usr/local/bin/ngrok, so shutil.which() is not reliable here —
        # it finds the shim first.  Check known system binary paths explicitly.
        system_ngrok_candidates = ["/usr/local/bin/ngrok", "/usr/bin/ngrok"]
        system_ngrok = next(
            (p for p in system_ngrok_candidates if os.path.isfile(p) and os.access(p, os.X_OK)),
            None,
        )
        if system_ngrok:
            resolved_ngrok_path = system_ngrok
        else:
            default_conf = conf.get_default()
            if not os.path.exists(default_conf.ngrok_path):
                installer.install_ngrok(default_conf.ngrok_path)
            resolved_ngrok_path = default_conf.ngrok_path

        async with self._lock:
            # Re-checked so a disconnect that already cleaned up is not followed by a new
            # working directory nobody removes.
            if not self._is_running or self._tunnel is not None or self._start_task is not None:
                return
            # Synchronous on purpose: in a thread, a cancelled caller would release the lock
            # while the thread still creates the working directory disconnect() cleans up.
            ngrok_path = self._prepare_binary(resolved_ngrok_path)
            self._config = PyngrokConfig(
                auth_token=self._auth_token,
                region=self._region if self._region else "eu",
                config_path=os.path.join(self._working_directory, "ngrok.yml"),
                ngrok_path=ngrok_path,
            )
            start_task = asyncio.create_task(self._start_tunnel())
            self._start_task = start_task

        # Shielded because cancelling the caller cannot stop the thread starting ngrok:
        # the task adopts the tunnel, or cleans up itself once disconnect() has begun.
        await asyncio.shield(start_task)

        # Not in the start task, so cancelling the caller also cancels a slow callback and
        # disconnect() never waits for it.
        if self._is_running and self._public_url and self._on_url_set:
            await self._on_url_set(self._public_url)

    async def _start_tunnel(self):
        def _start():
            addr = f"{self._host}:{self._port}"
            return ngrok.connect(addr, "http", domain=self._domain, pyngrok_config=self._config)

        new_tunnel = None
        try:
            new_tunnel = await asyncio.to_thread(_start)
        finally:
            async with self._lock:
                try:
                    if not self._is_running:
                        # disconnect() may have stopped waiting, so this task cleans up
                        # after itself whether or not the start succeeded.
                        if new_tunnel is not None:
                            logger.info("Disconnect called during connection, rolling back tunnel.")
                        await asyncio.to_thread(self._roll_back_start, new_tunnel)
                    elif new_tunnel is not None:
                        self._tunnel = new_tunnel
                        self._public_url = self._tunnel.public_url
                        logger.info("Tunnel established: {}", self._public_url)
                finally:
                    self._start_task = None

    def _roll_back_start(self, new_tunnel) -> None:
        try:
            if new_tunnel is not None:
                ngrok.disconnect(new_tunnel.public_url, pyngrok_config=self._config)
        except Exception as e:
            logger.debug("Rollback disconnect warning: {}", e)
        finally:
            self._stop_process_and_remove_working_directory()

    def _prepare_binary(self, source_path: str) -> str:
        """Place the ngrok binary in a private working directory (0700 on POSIX), created
        exclusively.

        An entry already at the binary path is refused, never adopted. There is no integrity
        check of the binary after placement.

        Raises:
            FileExistsError: Something this tunnel did not create occupies the binary path.
            NgrokWorkingDirectoryError: The directory is not private, or the binary is gone.
        """
        if self._working_directory is None:
            self._working_directory = tempfile.mkdtemp(prefix="ngrok_")
            self._require_private_working_directory()
        ngrok_path = os.path.join(self._working_directory, "ngrok")

        if not self._binary_placed:
            self._place_binary(source_path, ngrok_path)
            self._binary_placed = True

        # pyngrok downloads and runs a fresh binary when the path is missing; exists() is also
        # False for a symlink whose source is gone. The binary was ours, so the next attempt
        # starts from a fresh working directory.
        if not os.path.exists(ngrok_path):
            self._stop_process_and_remove_working_directory()
            raise NgrokWorkingDirectoryError(f"Refusing to run ngrok: {ngrok_path} is missing.")
        return ngrok_path

    def _require_private_working_directory(self) -> None:
        # No geteuid means Windows, where os.stat reports no meaningful POSIX mode or owner.
        if not hasattr(os, "geteuid"):
            return
        directory_status = os.stat(self._working_directory)
        is_private = (
            stat.S_IMODE(directory_status.st_mode) == 0o700
            and directory_status.st_uid == os.geteuid()
        )
        if not is_private:
            working_directory = self._working_directory
            self._remove_working_directory()
            raise NgrokWorkingDirectoryError(
                f"Refusing to run ngrok: {working_directory} is not a private 0700 directory."
            )

    def _place_binary(self, source_path: str, ngrok_path: str) -> None:
        try:
            os.symlink(source_path, ngrok_path)
            return
        except FileExistsError:
            raise
        except OSError:
            logger.debug("Symlinks unsupported, copying the ngrok binary instead.")

        # O_EXCL fails on any existing entry, including a planted symlink.
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        with open(source_path, "rb") as source_file:
            file_descriptor = os.open(ngrok_path, flags, 0o700)
            try:
                with os.fdopen(file_descriptor, "wb") as destination_file:
                    shutil.copyfileobj(source_file, destination_file)
            except BaseException:
                # This tunnel created the partial copy, so discard the directory; the file is
                # already closed here, which Windows needs before it can be removed.
                self._remove_working_directory()
                raise

    def _stop_process_and_remove_working_directory(self) -> None:
        # pyngrok registers the process before its later startup steps can raise, so a
        # failed connect can still leave a running ngrok behind.
        try:
            if self._config is not None:
                pyngrok.process.kill_process(self._config.ngrok_path)
        finally:
            self._remove_working_directory()

    def _remove_working_directory(self) -> None:
        if self._working_directory is not None:
            shutil.rmtree(self._working_directory, ignore_errors=True)
        self._working_directory = None
        self._binary_placed = False

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
                            "Reconnection attempt failed: {}. Next try in {}s",
                            e,
                            self._reconnect_timeout,
                        )
        except asyncio.CancelledError:
            logger.debug("Monitor task received cancellation.")
            raise
        finally:
            self._is_running = False

    async def _stop_in_flight_start(self, start_task: asyncio.Task) -> bool:
        """Kill the starting ngrok process, then wait a bounded time for the start task.

        pyngrok registers the process before it blocks reading the process output, so the
        kill ends that read and the start usually fails within milliseconds. The bounded
        wait covers a start that had not spawned the process yet; pyngrok checks its startup
        timeout only between reads, so the start is not guaranteed to end within it. The
        start task cleans up after itself either way, since _is_running is already False.

        Returns:
            Whether the start task finished within the wait.
        """
        config = self._config
        try:
            await asyncio.to_thread(pyngrok.process.kill_process, config.ngrok_path)
        except Exception as e:
            logger.debug("Killing the starting ngrok process on port {} failed: {}", self._port, e)

        # ngrok.connect makes up to two API requests after startup: creating the tunnel, then
        # fetching it again (ngrok v2) or its edge.
        timeout = config.startup_timeout + 2 * config.request_timeout + START_WAIT_SLACK_SECONDS
        try:
            await asyncio.wait_for(asyncio.shield(start_task), timeout)
        except TimeoutError:
            logger.warning(
                "ngrok start on port {} still running after {}s; it cleans up when it finishes.",
                self._port,
                timeout,
            )
            return False
        except Exception as e:
            logger.debug("ngrok start on port {} failed during disconnect: {}", self._port, e)
        return True

    async def disconnect(self):
        logger.info("Disconnecting ngrok tunnel on port {}...", self._port)
        self._is_running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            with contextlib.suppress(TimeoutError, asyncio.CancelledError):
                await asyncio.wait_for(self._monitor_task, timeout=1.0)
            self._monitor_task = None

        # Not under the lock: the start task takes it to clean up. If the start is still
        # running after the wait, it owns the process and directory, so stop here.
        start_task = self._start_task
        if start_task is not None and not await self._stop_in_flight_start(start_task):
            return

        async with self._lock:
            if self._tunnel and self._config:
                url_to_disconnect = self._tunnel.public_url

                def _close():
                    try:
                        ngrok.disconnect(url_to_disconnect, pyngrok_config=self._config)
                    except Exception as e:
                        logger.debug("Disconnect warning: {}", e)

                try:
                    await asyncio.to_thread(_close)
                    logger.info("Ngrok tunnel {} closed successfully.", url_to_disconnect)
                except Exception:
                    logger.exception("Failed to disconnect tunnel {}", url_to_disconnect)
                finally:
                    self._tunnel = None
                    self._public_url = None

            try:
                await asyncio.to_thread(self._stop_process_and_remove_working_directory)
            except Exception:
                logger.exception("Failed to stop ngrok process on port {}", self._port)
