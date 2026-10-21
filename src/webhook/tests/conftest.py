import asyncio
import json
import os
import stat
import tempfile
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fakeredis import FakeAsyncRedis

from app.core.settings import settings
from app.main import create_app
from app.services.redis_service import RedisService, get_redis_service
from app.services.tunnel_registry import TunnelRegistry, get_tunnel_registry


@pytest.fixture
async def redis_service():
    """The real RedisService, on an in-memory Redis."""
    service = RedisService(
        host="unused", port=0, webhook_channel=settings.WEBHOOK_MESSAGE_CHANNEL, password=""
    )
    service.client = FakeAsyncRedis(decode_responses=True)
    yield service
    await service.client.aclose()


@pytest.fixture
async def received_events(redis_service):
    """Stands in for Django's webhook listener: subscribes to the webhook channel and
    returns `received()`, which collects every event published within `timeout` seconds."""
    pubsub = redis_service.client.pubsub()
    await pubsub.subscribe(settings.WEBHOOK_MESSAGE_CHANNEL)
    await pubsub.get_message(timeout=1)

    async def received(timeout: float = 0.2) -> list[dict]:
        events = []
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.02)
            if message is not None:
                events.append(json.loads(message["data"]))
        return events

    yield received
    await pubsub.aclose()


@pytest.fixture
def tunnel_registry(redis_service):
    return TunnelRegistry(redis_service=redis_service)


@pytest.fixture
async def client(redis_service, tunnel_registry):
    """HTTP client for the app; no lifespan runs, so no tunnel or listener starts."""
    app = create_app()
    app.dependency_overrides[get_redis_service] = lambda: redis_service
    app.dependency_overrides[get_tunnel_registry] = lambda: tunnel_registry
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://webhook") as http_client:
        yield http_client


@pytest.fixture
def lifespan_dependencies():
    """Stub Redis, the listener and the startup sweep for running `lifespan` directly.

    Yields the `close_redis_connection` mock.
    """
    redis_service = AsyncMock()
    redis_service.client.publish = AsyncMock(return_value=1)
    close_redis_connection = AsyncMock()
    with (
        patch("app.main.get_redis_service", new=AsyncMock(return_value=redis_service)),
        patch("app.main.close_redis_connection", new=close_redis_connection),
        patch("app.main.listen_redis", new=AsyncMock()),
        patch("app.main.remove_stale_working_directories"),
    ):
        yield close_redis_connection


class _ReportedStatus:
    """Stat result with chosen permission bits, file type or owner; every other field,
    including the timestamps and inode, is real."""

    def __init__(self, status, permissions=None, file_type=None, uid=None):
        self._status = status
        file_type = stat.S_IFMT(status.st_mode) if file_type is None else file_type
        permissions = stat.S_IMODE(status.st_mode) if permissions is None else permissions
        self.st_mode = file_type | permissions
        self.st_uid = status.st_uid if uid is None else uid

    def __getattr__(self, name):
        return getattr(self._status, name)


@pytest.fixture
def reported_status(monkeypatch):
    """Make os.stat and os.lstat report chosen permission bits, file type or owner.

    Returns `report(matches, *, permissions=None, file_type=None, uid=None)`, where
    `matches` takes the path as a string. The latest matching rule wins; every other path
    keeps its real status. Used to present POSIX modes and owners on Windows, and states a
    test cannot create for real (another user's directory, a world-writable parent).
    """
    rules = []

    def reporting(real_function):
        def patched(path, *args, **kwargs):
            status = real_function(path, *args, **kwargs)
            path_string = os.fspath(path)
            for matches, overrides in reversed(rules):
                if matches(path_string):
                    return _ReportedStatus(status, **overrides)
            return status

        return patched

    monkeypatch.setattr(os, "stat", reporting(os.stat))
    monkeypatch.setattr(os, "lstat", reporting(os.lstat))

    def report(matches, **overrides):
        rules.append((matches, overrides))

    return report


@pytest.fixture
def temp_root_status(ngrok_environment, reported_status):
    """Make the resolved temp root report `mode` (file type bits included) and `uid`."""
    resolved_temp_root = os.path.realpath(ngrok_environment.temp_root)

    def report(mode: int, uid: int):
        reported_status(
            lambda path: path == resolved_temp_root,
            file_type=stat.S_IFMT(mode),
            permissions=stat.S_IMODE(mode),
            uid=uid,
        )

    return report


@pytest.fixture
def ngrok_environment(tmp_path, monkeypatch):
    """Mocked pyngrok with a fake source binary and a private temp root for working
    directories, so NgrokTunnel runs its real file handling."""
    source_binary = tmp_path / "source" / "ngrok"
    source_binary.parent.mkdir()
    binary_content = b"fake-ngrok-binary"
    source_binary.write_bytes(binary_content)
    temp_root = tmp_path / "temp"
    temp_root.mkdir()
    # Set explicitly: under a 002 umask mkdir makes it group-writable, which the temp root
    # safety check rightly refuses.
    os.chmod(temp_root, 0o755)

    # os.access is only used to detect a system ngrok; disabling it forces the
    # pyngrok default binary, pointed here at the fake source.
    monkeypatch.setattr(os, "access", lambda *args, **kwargs: False)
    monkeypatch.setattr(tempfile, "tempdir", str(temp_root))

    with (
        patch("app.providers.tunnels.ngrok_tunnel.ngrok") as mock_ngrok,
        patch("app.providers.tunnels.ngrok_tunnel.pyngrok.process") as mock_process,
        patch("app.providers.tunnels.ngrok_tunnel.conf") as mock_conf,
    ):
        mock_conf.get_default.return_value.ngrok_path = str(source_binary)
        mock_tunnel = MagicMock()
        mock_tunnel.public_url = "https://real-ngrok-url.com"
        mock_ngrok.connect.return_value = mock_tunnel
        yield SimpleNamespace(
            ngrok=mock_ngrok,
            process=mock_process,
            source_binary=source_binary,
            binary_content=binary_content,
            temp_root=temp_root,
        )
