import os
import stat
import tempfile
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from app.main import create_app
from app.providers.tunnels.base import AbstractTunnelProvider
from app.services.tunnel_registry import TunnelRegistry
from src.shared.models import BaseTunnelConfigData


@pytest.fixture
def mock_redis_service():
    redis_mock = AsyncMock()
    redis_mock.publish_webhook.return_value = None
    redis_mock.client.publish = AsyncMock(return_value=1)
    return redis_mock


@pytest.fixture
def mock_tunnel_provider():
    tunnel = AsyncMock(spec=AbstractTunnelProvider)
    tunnel.public_url = "https://mock-tunnel.ngrok.io"
    return tunnel


@pytest.fixture
def tunnel_registry():
    """A fresh, unpopulated `TunnelRegistry` for route-level tests.

    `handle_webhook` resolves the inbound path via
    `TunnelRegistry.resolve_by_path`, which only reads `_tunnel_pool` -- no
    real tunnel connection is needed, so tests populate it directly via
    `register_tunnel_path` instead of going through `register()` (which
    would call out to a real provider).
    """
    return TunnelRegistry()


@pytest.fixture
def register_tunnel_path(tunnel_registry):
    """Register a path in `tunnel_registry` without connecting a real tunnel.

    Returns the `BaseTunnelConfigData` used, so tests can assert against its
    `unique_id`/`auth` if needed.
    """

    def _register(
        path: str,
        auth=None,
        org_id: int | None = 1,
    ) -> BaseTunnelConfigData:
        config = BaseTunnelConfigData(
            name=path,
            org_id=org_id,
            auth=auth,
        )
        tunnel_registry._tunnel_pool[config.unique_id] = (None, config)
        return config

    return _register


@pytest.fixture
def app(mock_redis_service):
    # The startup sweep is stubbed so no test removes anything from the real temp directory.
    with (
        patch("app.main.get_redis_service", new=AsyncMock(return_value=mock_redis_service)),
        patch("app.main.close_redis_connection", new=AsyncMock()),
        patch("app.main.listen_redis", new=AsyncMock()),
        patch("app.main.remove_stale_working_directories"),
    ):
        yield create_app()


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


@pytest.fixture
def client(app, mock_redis_service, tunnel_registry):
    from app.controllers.webhook_routes import get_redis_service, get_tunnel_registry

    app.dependency_overrides[get_redis_service] = lambda: mock_redis_service
    app.dependency_overrides[get_tunnel_registry] = lambda: tunnel_registry
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


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
