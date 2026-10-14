import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest

from app import main as main_module
from app.core.settings import settings
from app.main import lifespan
from app.services.tunnel_registry import TunnelRegistry, UnregisteredWebhookPathError
from src.shared.models import LocalhostConfigData, NgrokConfigData


class _FakeTunnel:
    """Tunnel whose disconnect can fail or hang until released."""

    def __init__(self, url="http://tunnel", fail=False, release: asyncio.Event | None = None):
        self.url = url
        self.disconnect_started = asyncio.Event()
        self.disconnect_finished = asyncio.Event()
        self.disconnected = False
        self._fail = fail
        self._release = release
        self._on_url_set = None

    async def connect(self):
        if self._on_url_set is not None:
            await self._on_url_set(self.url)

    async def disconnect(self):
        self.disconnect_started.set()
        try:
            if self._release is not None:
                await self._release.wait()
            if self._fail:
                raise RuntimeError("disconnect failed")
            self.disconnected = True
        finally:
            self.disconnect_finished.set()


class _ConnectBlockedUntilKilled:
    """ngrok.connect stand-in that blocks like pyngrok's startup read until the process
    is killed; with `fail_first`, the first start fails at once and the retry blocks."""

    def __init__(self, environment, fail_first=False):
        self.started = threading.Event()
        self.killed = threading.Event()
        self._fail_next = fail_first
        environment.ngrok.connect.side_effect = self.connect
        environment.process.kill_process.side_effect = lambda *args: self.killed.set()

    def connect(self, *args, **kwargs):
        if self._fail_next:
            self._fail_next = False
            raise RuntimeError("ngrok failed to start")
        self.started.set()
        assert self.killed.wait(timeout=5), "ngrok process was never killed"
        raise RuntimeError("ngrok process was killed")


async def _register_fake(registry, tunnel, name):
    config = LocalhostConfigData(name=name, org_id=1)
    with patch("app.services.tunnel_registry.get_provider", return_value=tunnel):
        await registry.register(config)
    return config


async def _registry_with(*tunnels, redis_service=None):
    registry = TunnelRegistry(redis_service=redis_service)
    for index, tunnel in enumerate(tunnels):
        await _register_fake(registry, tunnel, f"hook-{index}")
    return registry


async def _published_tunnel_urls(redis_service) -> dict[str, str]:
    return await redis_service.client.hgetall(settings.TUNNEL_URLS_HASH_KEY)


async def _is_registered(registry, path) -> bool:
    try:
        await registry.resolve_by_path(path)
    except UnregisteredWebhookPathError:
        return False
    return True


async def _run_lifespan(registry, timeout=3, while_running=None):
    async def run():
        async with lifespan(MagicMock()):
            if while_running is not None:
                await while_running()

    with patch("app.main.get_tunnel_registry", return_value=registry):
        await asyncio.wait_for(run(), timeout=timeout)


async def test_failing_disconnect_still_deletes_its_url_and_unregisters_the_others(
    redis_service,
):
    failing = _FakeTunnel(fail=True)
    healthy = _FakeTunnel()
    registry = await _registry_with(failing, healthy, redis_service=redis_service)
    assert len(await _published_tunnel_urls(redis_service)) == 2

    await registry.unregister_all()

    assert healthy.disconnected
    assert await _published_tunnel_urls(redis_service) == {}
    assert not await _is_registered(registry, "hook-0")


async def test_unregister_all_does_not_swallow_cancellation():
    release = asyncio.Event()
    hanging = _FakeTunnel(release=release)
    registry = await _registry_with(hanging)
    unregister_task = asyncio.create_task(registry.unregister_all())
    await asyncio.wait_for(hanging.disconnect_started.wait(), timeout=3)

    unregister_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await unregister_task
    release.set()
    await asyncio.wait_for(hanging.disconnect_finished.wait(), timeout=3)


async def test_lifespan_shutdown_is_bounded_and_deletes_urls_when_a_tunnel_hangs(
    lifespan_dependencies, redis_service, monkeypatch
):
    monkeypatch.setattr(main_module, "TUNNEL_SHUTDOWN_TIMEOUT_SECONDS", 0.2)
    release = asyncio.Event()
    hanging = _FakeTunnel(release=release)
    healthy = _FakeTunnel()
    registry = await _registry_with(hanging, healthy, redis_service=redis_service)

    try:
        await _run_lifespan(registry)
    finally:
        release.set()

    assert healthy.disconnected
    assert not hanging.disconnected
    # The hung tunnel's URL is deleted even though its disconnect never finished.
    assert await _published_tunnel_urls(redis_service) == {}
    lifespan_dependencies.assert_awaited_once()
    await asyncio.wait_for(hanging.disconnect_finished.wait(), timeout=3)


async def test_lifespan_shutdown_deletes_every_tunnel_url_before_closing_redis(
    lifespan_dependencies, redis_service
):
    urls_when_redis_closed = []

    async def close_redis():
        urls_when_redis_closed.append(await _published_tunnel_urls(redis_service))

    lifespan_dependencies.side_effect = close_redis
    registry = await _registry_with(_FakeTunnel(), _FakeTunnel(), redis_service=redis_service)

    await _run_lifespan(registry)

    assert urls_when_redis_closed == [{}]


async def test_lifespan_shutdown_disconnects_every_tunnel_and_removes_working_directories(
    ngrok_environment, lifespan_dependencies
):
    registry = TunnelRegistry()
    for index in range(2):
        await registry.register(
            NgrokConfigData(name=f"hook-{index}", org_id=1, auth_token="test-token")
        )
    assert len(list(ngrok_environment.temp_root.iterdir())) == 2

    await _run_lifespan(registry)

    assert not await _is_registered(registry, "hook-0")
    assert not await _is_registered(registry, "hook-1")
    assert ngrok_environment.ngrok.disconnect.call_count == 2
    assert ngrok_environment.process.kill_process.call_count == 2
    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_lifespan_shutdown_kills_a_start_blocked_mid_reconnect(
    ngrok_environment, lifespan_dependencies, monkeypatch
):
    monkeypatch.setattr(settings, "WEBHOOK_TUNNEL_RECONNECT_TIMEOUT", 0)
    blocked_connect = _ConnectBlockedUntilKilled(ngrok_environment, fail_first=True)
    registry = TunnelRegistry()
    # The first start fails, so the tunnel is registered and its monitor retries.
    await registry.register(NgrokConfigData(name="hook", org_id=1, auth_token="test-token"))
    assert await asyncio.to_thread(blocked_connect.started.wait, 5)

    try:
        # Well inside the 8s shutdown budget: killing the process ends the blocked start.
        await _run_lifespan(registry, timeout=2)
    finally:
        blocked_connect.killed.set()

    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_lifespan_shutdown_is_bounded_when_the_listener_is_stuck_in_register(
    ngrok_environment, lifespan_dependencies, monkeypatch
):
    monkeypatch.setattr(main_module, "TUNNEL_SHUTDOWN_TIMEOUT_SECONDS", 0.3)
    connect_started = threading.Event()
    connect_release = threading.Event()

    # Ignores the kill, so the new tunnel's disconnect waits for its full backstop.
    def connect_ignoring_kill(*args, **kwargs):
        connect_started.set()
        assert connect_release.wait(timeout=5), "test never released the blocked connect"
        raise RuntimeError("ngrok process ended")

    ngrok_environment.ngrok.connect.side_effect = connect_ignoring_kill
    registry = TunnelRegistry()
    config = NgrokConfigData(name="hook", org_id=1, auth_token="test-token")
    listener_finished = asyncio.Event()

    async def listener_stuck_in_register(redis_service, tunnel_registry):
        try:
            await tunnel_registry.register(config)
        finally:
            listener_finished.set()

    async def wait_for_blocked_start():
        assert await asyncio.to_thread(connect_started.wait, 5)

    with patch("app.main.listen_redis", new=listener_stuck_in_register):
        try:
            await _run_lifespan(registry, timeout=3, while_running=wait_for_blocked_start)
        finally:
            connect_release.set()

    lifespan_dependencies.assert_awaited_once()
    # The interrupted register() still disconnects its tunnel once the start ends.
    await asyncio.wait_for(listener_finished.wait(), timeout=5)
    assert not await _is_registered(registry, "hook")
    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_register_cancelled_mid_connect_leaves_no_live_tunnel(ngrok_environment):
    blocked_connect = _ConnectBlockedUntilKilled(ngrok_environment)
    registry = TunnelRegistry()
    config = NgrokConfigData(name="hook", org_id=1, auth_token="test-token")
    register_task = asyncio.create_task(registry.register(config))
    assert await asyncio.to_thread(blocked_connect.started.wait, 5)

    register_task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(register_task, timeout=3)
    finally:
        blocked_connect.killed.set()

    assert not await _is_registered(registry, "hook")
    ngrok_environment.ngrok.disconnect.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_register_cancelled_while_replacing_still_disconnects_the_old_tunnel(
    redis_service,
):
    release = asyncio.Event()
    old_tunnel = _FakeTunnel(url="http://old", release=release)
    new_tunnel = _FakeTunnel(url="http://new")
    registry = TunnelRegistry(redis_service=redis_service)
    config = await _register_fake(registry, old_tunnel, "hook")

    with patch("app.services.tunnel_registry.get_provider", return_value=new_tunnel):
        register_task = asyncio.create_task(registry.register(config))
        await asyncio.wait_for(old_tunnel.disconnect_started.wait(), timeout=3)
        register_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await register_task

    release.set()
    await asyncio.wait_for(old_tunnel.disconnect_finished.wait(), timeout=3)

    assert old_tunnel.disconnected
    assert await _published_tunnel_urls(redis_service) == {config.unique_id: "http://new"}
