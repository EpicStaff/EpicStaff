import asyncio
import threading
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app import main as main_module
from app.core.settings import settings
from app.main import lifespan
from app.providers.provider_factory import get_provider
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel
from app.services.tunnel_registry import TunnelRegistry
from src.shared.models import LocalhostConfigData, NgrokConfigData


class _FakeTunnel:
    def __init__(self, fail=False, release: asyncio.Event | None = None):
        self.disconnect_started = asyncio.Event()
        self.disconnect_finished = asyncio.Event()
        self.disconnected = False
        self._fail = fail
        self._release = release

    async def connect(self):
        pass

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
    """ngrok.connect stand-in that blocks like pyngrok's startup read until the process is killed."""

    def __init__(self, environment):
        self.started = threading.Event()
        self.killed = threading.Event()
        environment.ngrok.connect.side_effect = self.connect
        environment.process.kill_process.side_effect = lambda *args: self.killed.set()

    def connect(self, *args, **kwargs):
        self.started.set()
        assert self.killed.wait(timeout=5), "ngrok process was never killed"
        raise RuntimeError("ngrok process was killed")


def _registry_with(*tunnels, redis_service=None):
    registry = TunnelRegistry(redis_service=redis_service)
    for index, tunnel in enumerate(tunnels):
        config = LocalhostConfigData(name=f"hook-{index}", org_id=1)
        registry._tunnel_pool[config.unique_id] = (tunnel, config)
    return registry


def _make_ngrok_provider() -> NgrokTunnel:
    return NgrokTunnel(port=settings.WEBHOOK_PORT, auth_token="test-token")


@pytest.fixture
def lifespan_dependencies():
    redis_service = AsyncMock()
    redis_service.client.publish = AsyncMock(return_value=1)
    close_redis_connection = AsyncMock()
    with (
        patch("app.main.get_redis_service", new=AsyncMock(return_value=redis_service)),
        patch("app.main.close_redis_connection", new=close_redis_connection),
        patch("app.main.listen_redis", new=AsyncMock()),
    ):
        yield close_redis_connection


async def _run_lifespan(registry, timeout=3, while_running=None):
    async def run():
        async with lifespan(MagicMock()):
            if while_running is not None:
                await while_running()

    with patch("app.main.get_tunnel_registry", return_value=registry):
        await asyncio.wait_for(run(), timeout=timeout)


async def test_failing_disconnect_still_deletes_its_url_and_unregisters_the_others():
    redis_service = AsyncMock()
    failing = _FakeTunnel(fail=True)
    healthy = _FakeTunnel()
    registry = _registry_with(failing, healthy, redis_service=redis_service)
    unique_ids = list(registry._tunnel_pool)

    await registry.unregister_all()

    assert healthy.disconnected
    assert registry._tunnel_pool == {}
    deleted_ids = [call.args[0] for call in redis_service.delete_tunnel_url.await_args_list]
    assert sorted(deleted_ids) == sorted(unique_ids)


async def test_unregister_all_does_not_swallow_cancellation():
    release = asyncio.Event()
    hanging = _FakeTunnel(release=release)
    registry = _registry_with(hanging)
    unregister_task = asyncio.create_task(registry.unregister_all())
    await asyncio.wait_for(hanging.disconnect_started.wait(), timeout=3)

    unregister_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await unregister_task
    release.set()
    await asyncio.wait_for(hanging.disconnect_finished.wait(), timeout=3)


async def test_lifespan_shutdown_is_bounded_and_deletes_urls_when_a_tunnel_hangs(
    lifespan_dependencies, monkeypatch
):
    monkeypatch.setattr(main_module, "TUNNEL_SHUTDOWN_TIMEOUT_SECONDS", 0.2)
    redis_service = AsyncMock()
    release = asyncio.Event()
    hanging = _FakeTunnel(release=release)
    healthy = _FakeTunnel()
    registry = _registry_with(hanging, healthy, redis_service=redis_service)
    unique_ids = list(registry._tunnel_pool)

    try:
        await _run_lifespan(registry)
    finally:
        release.set()

    assert healthy.disconnected
    assert not hanging.disconnected
    # The hung tunnel's URL is deleted even though its disconnect never finished.
    deleted_ids = [call.args[0] for call in redis_service.delete_tunnel_url.await_args_list]
    assert sorted(deleted_ids) == sorted(unique_ids)
    lifespan_dependencies.assert_awaited_once()
    await asyncio.wait_for(hanging.disconnect_finished.wait(), timeout=3)


async def test_lifespan_shutdown_deletes_every_tunnel_url_before_closing_redis(
    lifespan_dependencies,
):
    events: list[str] = []
    redis_service = AsyncMock()
    redis_service.delete_tunnel_url.side_effect = lambda unique_id: events.append(unique_id)
    lifespan_dependencies.side_effect = lambda: events.append("close redis")
    registry = _registry_with(_FakeTunnel(), _FakeTunnel(), redis_service=redis_service)
    unique_ids = list(registry._tunnel_pool)

    await _run_lifespan(registry)

    assert sorted(events[:-1]) == sorted(unique_ids)
    assert events[-1] == "close redis"


async def test_lifespan_shutdown_disconnects_every_tunnel_and_removes_working_directories(
    ngrok_environment, lifespan_dependencies
):
    registry = TunnelRegistry()
    providers = []
    for index in range(2):
        config = NgrokConfigData(name=f"hook-{index}", org_id=1, auth_token="test-token")
        provider = _make_ngrok_provider()
        await provider.connect()
        registry._tunnel_pool[config.unique_id] = (provider, config)
        providers.append(provider)
    assert len(list(ngrok_environment.temp_root.iterdir())) == 2

    await _run_lifespan(registry)

    assert registry._tunnel_pool == {}
    assert all(provider.public_url is None for provider in providers)
    assert ngrok_environment.ngrok.disconnect.call_count == 2
    assert ngrok_environment.process.kill_process.call_count == 2
    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_lifespan_shutdown_kills_a_start_blocked_mid_connect(
    ngrok_environment, lifespan_dependencies
):
    blocked_connect = _ConnectBlockedUntilKilled(ngrok_environment)
    provider = _make_ngrok_provider()
    config = NgrokConfigData(name="hook", org_id=1, auth_token="test-token")
    registry = TunnelRegistry()
    registry._tunnel_pool[config.unique_id] = (provider, config)
    connect_task = asyncio.create_task(provider.connect())
    assert await asyncio.to_thread(blocked_connect.started.wait, 5)

    try:
        # Well inside the 8s shutdown budget: killing the process ends the blocked start.
        await _run_lifespan(registry, timeout=2)
    finally:
        blocked_connect.killed.set()
        await asyncio.wait_for(connect_task, timeout=5)

    assert provider._tunnel is None
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
    assert registry._tunnel_pool == {}
    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_register_cancelled_mid_connect_leaves_no_live_tunnel(ngrok_environment):
    blocked_connect = _ConnectBlockedUntilKilled(ngrok_environment)
    created_tunnels = []

    def create_provider(config):
        tunnel = get_provider(config)
        created_tunnels.append(tunnel)
        return tunnel

    registry = TunnelRegistry()
    config = NgrokConfigData(name="hook", org_id=1, auth_token="test-token")
    with patch("app.services.tunnel_registry.get_provider", side_effect=create_provider):
        register_task = asyncio.create_task(registry.register(config))
        assert await asyncio.to_thread(blocked_connect.started.wait, 5)

        register_task.cancel()
        try:
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(register_task, timeout=3)
        finally:
            blocked_connect.killed.set()

    (tunnel,) = created_tunnels
    assert registry._tunnel_pool == {}
    assert not tunnel.is_active
    assert tunnel._start_task is None
    assert tunnel._tunnel is None
    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_register_cancelled_while_replacing_still_disconnects_the_old_tunnel():
    release = asyncio.Event()
    old_tunnel = _FakeTunnel(release=release)
    new_tunnel = _FakeTunnel()
    config = LocalhostConfigData(name="hook", org_id=1)
    registry = TunnelRegistry()
    registry._tunnel_pool[config.unique_id] = (old_tunnel, config)

    with patch("app.services.tunnel_registry.get_provider", return_value=new_tunnel):
        register_task = asyncio.create_task(registry.register(config))
        await asyncio.wait_for(old_tunnel.disconnect_started.wait(), timeout=3)
        register_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await register_task

    release.set()
    await asyncio.wait_for(old_tunnel.disconnect_finished.wait(), timeout=3)

    assert old_tunnel.disconnected
    assert registry._tunnel_pool[config.unique_id][0] is new_tunnel
