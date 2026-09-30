import asyncio
import errno
import os
import shutil
import stat
import tempfile
import threading

import pytest
from unittest.mock import patch, ANY
from app.providers.tunnels import ngrok_tunnel as ngrok_tunnel_module
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel, NgrokWorkingDirectoryError
from app.core.settings import settings


def _symlinks_supported(directory) -> bool:
    probe = directory / "symlink_probe"
    try:
        os.symlink(directory, probe)
    except OSError:
        return False
    os.remove(probe)
    return True


def _refuse_symlink(*args, **kwargs):
    raise OSError(errno.EPERM, "symlinks unsupported")


def _make_provider() -> NgrokTunnel:
    return NgrokTunnel(port=settings.WEBHOOK_PORT, auth_token="test-token")


def _started_config(environment):
    return environment.ngrok.connect.call_args.kwargs["pyngrok_config"]


def _stat_reporting_mode(real_stat, mode):
    """os.stat stand-in that reports `mode` for ngrok working directories."""

    def patched_stat(path, *args, **kwargs):
        status = real_stat(path, *args, **kwargs)
        if os.path.basename(path).startswith("ngrok_"):
            fields = list(status)
            fields[stat.ST_MODE] = stat.S_IFDIR | mode
            return os.stat_result(fields)
        return status

    return patched_stat


@pytest.mark.asyncio
async def test_ngrok_connect_and_disconnect(ngrok_environment):
    port = settings.WEBHOOK_PORT
    domain = "example.ngrok.app"
    provider = NgrokTunnel(port=port, auth_token="test-token", domain=domain)

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_called_once_with(
        f"localhost:{port}", "http", domain=domain, pyngrok_config=ANY
    )
    assert provider.public_url == "https://real-ngrok-url.com"

    await provider.disconnect()

    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        "https://real-ngrok-url.com", pyngrok_config=ANY
    )
    ngrok_environment.process.kill_process.assert_called()
    assert provider.public_url is None


def test_construction_leaves_no_working_directory(ngrok_environment):
    _make_provider()

    assert list(ngrok_environment.temp_root.iterdir()) == []


@pytest.mark.asyncio
async def test_connect_uses_private_working_directory(ngrok_environment):
    provider = _make_provider()

    await provider.connect()

    working_directories = list(ngrok_environment.temp_root.iterdir())
    assert len(working_directories) == 1
    working_directory = working_directories[0]
    assert working_directory.name.startswith("ngrok_")
    config = _started_config(ngrok_environment)
    assert config.ngrok_path == str(working_directory / "ngrok")
    assert config.config_path == str(working_directory / "ngrok.yml")
    with open(config.ngrok_path, "rb") as binary_file:
        assert binary_file.read() == ngrok_environment.binary_content
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(working_directory).st_mode) == 0o700

    await provider.disconnect()


@pytest.mark.asyncio
async def test_reconnect_reuses_working_directory(ngrok_environment):
    provider = _make_provider()
    await provider.connect()
    first_path = _started_config(ngrok_environment).ngrok_path

    provider._tunnel = None
    await provider._establish_connection()

    assert ngrok_environment.ngrok.connect.call_count == 2
    assert _started_config(ngrok_environment).ngrok_path == first_path

    await provider.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("planted_kind", ["file", "directory"])
async def test_preplanted_binary_path_is_not_executed(
    ngrok_environment, tmp_path, monkeypatch, planted_kind
):
    planted_directory = tmp_path / "planted"
    # 0700 like a real mkdtemp result, so only the planted entry is what gets refused.
    planted_directory.mkdir(mode=0o700)
    planted_binary = planted_directory / "ngrok"
    if planted_kind == "file":
        planted_binary.write_bytes(b"malicious")
    else:
        planted_binary.mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(planted_directory))
    provider = _make_provider()

    await provider.connect()
    # A second attempt must refuse again rather than recover on its own.
    provider._tunnel = None
    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert planted_directory.is_dir()
    if planted_kind == "file":
        assert planted_binary.read_bytes() == b"malicious"
    else:
        assert planted_binary.is_dir()

    await provider.disconnect()


@pytest.mark.asyncio
async def test_copies_binary_when_symlinks_unsupported(ngrok_environment, monkeypatch):
    monkeypatch.setattr(os, "symlink", _refuse_symlink)
    provider = _make_provider()

    await provider.connect()

    ngrok_path = _started_config(ngrok_environment).ngrok_path
    assert not os.path.islink(ngrok_path)
    with open(ngrok_path, "rb") as binary_file:
        assert binary_file.read() == ngrok_environment.binary_content
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(ngrok_path).st_mode) == 0o700

    await provider.disconnect()


@pytest.mark.asyncio
@pytest.mark.parametrize("removal", ["binary deleted", "symlink source deleted"])
async def test_missing_binary_is_not_downloaded_or_run(
    ngrok_environment, tmp_path, monkeypatch, removal
):
    if removal == "symlink source deleted":
        if not _symlinks_supported(tmp_path):
            pytest.skip("Symlinks unsupported on this platform")
    else:
        monkeypatch.setattr(os, "symlink", _refuse_symlink)
    provider = _make_provider()
    await provider.connect()
    ngrok_path = _started_config(ngrok_environment).ngrok_path
    if removal == "binary deleted":
        os.remove(ngrok_path)
    else:
        os.remove(ngrok_environment.source_binary)
        assert os.path.islink(ngrok_path)

    provider._tunnel = None
    with (
        patch("app.providers.tunnels.ngrok_tunnel.installer") as mock_installer,
        pytest.raises(NgrokWorkingDirectoryError, match="is missing"),
    ):
        await provider._establish_connection()

    # ngrok.connect is where pyngrok would download a replacement into the working directory.
    assert ngrok_environment.ngrok.connect.call_count == 1
    if removal == "binary deleted":
        mock_installer.install_ngrok.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


@pytest.mark.asyncio
async def test_next_attempt_after_binary_vanished_uses_fresh_working_directory(
    ngrok_environment, monkeypatch
):
    monkeypatch.setattr(os, "symlink", _refuse_symlink)
    provider = _make_provider()
    await provider.connect()
    first_path = _started_config(ngrok_environment).ngrok_path
    os.remove(first_path)
    provider._tunnel = None
    with pytest.raises(NgrokWorkingDirectoryError):
        await provider._establish_connection()

    await provider._establish_connection()

    second_path = _started_config(ngrok_environment).ngrok_path
    assert ngrok_environment.ngrok.connect.call_count == 2
    assert os.path.dirname(second_path) != os.path.dirname(first_path)
    with open(second_path, "rb") as binary_file:
        assert binary_file.read() == ngrok_environment.binary_content

    await provider.disconnect()


@pytest.mark.asyncio
async def test_working_directory_that_is_not_private_is_refused(ngrok_environment, monkeypatch):
    real_stat = os.stat
    # geteuid is patched so the check also runs on Windows, which has no geteuid.
    monkeypatch.setattr(
        os, "geteuid", lambda: real_stat(ngrok_environment.temp_root).st_uid, raising=False
    )
    monkeypatch.setattr(os, "stat", _stat_reporting_mode(real_stat, 0o755))
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


@pytest.mark.asyncio
async def test_working_directory_owned_by_another_user_is_refused(ngrok_environment, monkeypatch):
    real_stat = os.stat
    monkeypatch.setattr(
        os, "geteuid", lambda: real_stat(ngrok_environment.temp_root).st_uid + 1, raising=False
    )
    # Windows reports st_mode 0o777 for directories, so present a private mode there.
    monkeypatch.setattr(os, "stat", _stat_reporting_mode(real_stat, 0o700))
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


@pytest.mark.asyncio
async def test_disconnect_removes_working_directory(ngrok_environment):
    provider = _make_provider()
    await provider.connect()

    await provider.disconnect()

    assert list(ngrok_environment.temp_root.iterdir()) == []
    ngrok_environment.process.kill_process.assert_called_once_with(
        _started_config(ngrok_environment).ngrok_path
    )


@pytest.mark.asyncio
async def test_disconnect_after_failed_connect_removes_working_directory(ngrok_environment):
    ngrok_environment.ngrok.connect.side_effect = RuntimeError("ngrok failed to start")
    provider = _make_provider()
    await provider.connect()
    working_directories = list(ngrok_environment.temp_root.iterdir())
    assert len(working_directories) == 1

    await provider.disconnect()

    ngrok_environment.process.kill_process.assert_called_once_with(
        str(working_directories[0] / "ngrok")
    )
    ngrok_environment.ngrok.disconnect.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []


def _connect_while_disconnecting(environment, provider):
    mock_tunnel = environment.ngrok.connect.return_value

    def connect(*args, **kwargs):
        provider._is_running = False
        return mock_tunnel

    environment.ngrok.connect.side_effect = connect
    return mock_tunnel


@pytest.mark.asyncio
async def test_rollback_removes_working_directory(ngrok_environment):
    provider = _make_provider()
    mock_tunnel = _connect_while_disconnecting(ngrok_environment, provider)
    provider._is_running = True

    await provider._establish_connection()

    assert provider._tunnel is None
    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        mock_tunnel.public_url, pyngrok_config=ANY
    )
    ngrok_environment.process.kill_process.assert_called_once()
    assert list(ngrok_environment.temp_root.iterdir()) == []


@pytest.mark.asyncio
async def test_rollback_cleans_up_when_ngrok_disconnect_fails(ngrok_environment):
    provider = _make_provider()
    _connect_while_disconnecting(ngrok_environment, provider)
    ngrok_environment.ngrok.disconnect.side_effect = RuntimeError("ngrok API unreachable")
    provider._is_running = True

    await provider._establish_connection()

    config = _started_config(ngrok_environment)
    ngrok_environment.process.kill_process.assert_called_once_with(config.ngrok_path)
    assert list(ngrok_environment.temp_root.iterdir()) == []


@pytest.mark.asyncio
async def test_reconnect_after_disconnect_uses_fresh_working_directory(ngrok_environment):
    provider = _make_provider()
    await provider.connect()
    first_path = _started_config(ngrok_environment).ngrok_path
    await provider.disconnect()

    await provider.connect()
    second_path = _started_config(ngrok_environment).ngrok_path

    assert os.path.dirname(first_path) != os.path.dirname(second_path)
    assert os.path.exists(second_path)

    await provider.disconnect()


class _BlockingReconnect:
    """ngrok.connect stand-in: the first call fails, the monitor's retry blocks until released."""

    def __init__(self, tunnel):
        self.tunnel = tunnel
        self.started = threading.Event()
        self.release = threading.Event()
        self.killed = threading.Event()
        self.events: list[str] = []
        self.call_count = 0

    def __call__(self, *args, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("initial connect failed")
        self.started.set()
        assert self.release.wait(timeout=5), "test never released the blocked connect"
        self.events.append("connect returned")
        return self.tunnel

    def kill(self, *args):
        self.events.append("kill")
        self.killed.set()


@pytest.fixture
async def provider_blocked_mid_reconnect(ngrok_environment):
    blocking_connect = _BlockingReconnect(ngrok_environment.ngrok.connect.return_value)
    ngrok_environment.ngrok.connect.side_effect = blocking_connect
    ngrok_environment.process.kill_process.side_effect = blocking_connect.kill
    provider = NgrokTunnel(port=settings.WEBHOOK_PORT, auth_token="test-token", reconnect_timeout=0)
    await provider.connect()
    assert await asyncio.to_thread(blocking_connect.started.wait, 5)
    yield provider, blocking_connect
    blocking_connect.release.set()
    await provider.disconnect()


@pytest.mark.asyncio
async def test_disconnect_mid_reconnect_rolls_back_late_tunnel(
    ngrok_environment, provider_blocked_mid_reconnect
):
    provider, blocking_connect = provider_blocked_mid_reconnect
    working_directory = provider._working_directory

    disconnect_task = asyncio.create_task(provider.disconnect())
    assert await asyncio.to_thread(blocking_connect.killed.wait, 5)
    blocking_connect.release.set()
    await asyncio.wait_for(disconnect_task, timeout=5)

    assert provider._tunnel is None
    assert provider.public_url is None
    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        blocking_connect.tunnel.public_url, pyngrok_config=ANY
    )
    # Killed first to end the blocked start, then again by the rollback of the late tunnel.
    assert blocking_connect.events[0] == "kill"
    connect_returned_at = blocking_connect.events.index("connect returned")
    assert "kill" in blocking_connect.events[connect_returned_at + 1 :]
    assert not os.path.exists(working_directory)
    assert list(ngrok_environment.temp_root.iterdir()) == []


@pytest.mark.asyncio
async def test_disconnect_wait_for_hung_start_is_bounded(
    ngrok_environment, provider_blocked_mid_reconnect, monkeypatch
):
    provider, blocking_connect = provider_blocked_mid_reconnect
    monkeypatch.setattr(ngrok_tunnel_module, "START_WAIT_SLACK_SECONDS", 0.2)
    provider._config.startup_timeout = 0
    provider._config.request_timeout = 0
    ngrok_path = provider._config.ngrok_path
    start_task = provider._start_task

    await asyncio.wait_for(provider.disconnect(), timeout=3)

    assert not blocking_connect.release.is_set()
    # Killing the process is what ends pyngrok's blocking startup read.
    ngrok_environment.process.kill_process.assert_called_with(ngrok_path)

    blocking_connect.release.set()
    await asyncio.wait_for(start_task, timeout=5)

    assert provider._tunnel is None
    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        blocking_connect.tunnel.public_url, pyngrok_config=ANY
    )
    assert list(ngrok_environment.temp_root.iterdir()) == []


@pytest.mark.asyncio
async def test_hung_url_callback_does_not_block_disconnect(ngrok_environment):
    ngrok_environment.ngrok.connect.side_effect = [
        RuntimeError("initial connect failed"),
        ngrok_environment.ngrok.connect.return_value,
    ]
    callback_entered = asyncio.Event()

    async def hung_set_url(url: str):
        callback_entered.set()
        await asyncio.Event().wait()

    provider = NgrokTunnel(port=settings.WEBHOOK_PORT, auth_token="test-token", reconnect_timeout=0)
    provider._on_url_set = hung_set_url
    await provider.connect()
    await asyncio.wait_for(callback_entered.wait(), timeout=5)

    await asyncio.wait_for(provider.disconnect(), timeout=3)

    assert provider.public_url is None
    ngrok_environment.ngrok.disconnect.assert_called_once()
    assert list(ngrok_environment.temp_root.iterdir()) == []


@pytest.mark.asyncio
async def test_failed_copy_placement_recovers_on_next_attempt(ngrok_environment, monkeypatch):
    monkeypatch.setattr(os, "symlink", _refuse_symlink)
    real_copyfileobj = shutil.copyfileobj
    copy_calls = []

    def copy_fails_once(*args, **kwargs):
        copy_calls.append(args)
        if len(copy_calls) == 1:
            raise OSError(errno.ENOSPC, "No space left on device")
        return real_copyfileobj(*args, **kwargs)

    monkeypatch.setattr(shutil, "copyfileobj", copy_fails_once)
    provider = _make_provider()
    provider._is_running = True

    with pytest.raises(OSError, match="No space left"):
        await provider._establish_connection()

    assert provider._working_directory is None
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider._establish_connection()

    ngrok_environment.ngrok.connect.assert_called_once()
    with open(_started_config(ngrok_environment).ngrok_path, "rb") as binary_file:
        assert binary_file.read() == ngrok_environment.binary_content

    await provider.disconnect()
