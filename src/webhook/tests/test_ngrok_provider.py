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
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel
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


async def _wait_until(condition, timeout: float = 5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not condition():
        assert asyncio.get_running_loop().time() < deadline, "condition not met in time"
        await asyncio.sleep(0.01)


def _is_working_directory(path: str) -> bool:
    return os.path.basename(path).startswith("ngrok_")


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
async def test_retry_after_failed_start_reuses_working_directory(ngrok_environment):
    ngrok_environment.ngrok.connect.side_effect = [
        RuntimeError("ngrok failed to start"),
        ngrok_environment.ngrok.connect.return_value,
    ]
    provider = _make_provider()
    await provider.connect()
    first_path = _started_config(ngrok_environment).ngrok_path

    await provider.connect()

    assert provider.public_url == "https://real-ngrok-url.com"
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
async def test_missing_binary_is_not_downloaded_or_run_and_next_attempt_starts_fresh(
    ngrok_environment, tmp_path, monkeypatch, removal
):
    if removal == "symlink source deleted":
        if not _symlinks_supported(tmp_path):
            pytest.skip("Symlinks unsupported on this platform")
    else:
        monkeypatch.setattr(os, "symlink", _refuse_symlink)
    # The first start fails after the binary was placed, so the next attempt reuses it.
    ngrok_environment.ngrok.connect.side_effect = [
        RuntimeError("ngrok failed to start"),
        ngrok_environment.ngrok.connect.return_value,
    ]
    provider = _make_provider()
    await provider.connect()
    first_path = _started_config(ngrok_environment).ngrok_path
    if removal == "binary deleted":
        os.remove(first_path)
    else:
        os.remove(ngrok_environment.source_binary)
        assert os.path.islink(first_path)

    with patch("app.providers.tunnels.ngrok_tunnel.installer") as mock_installer:
        await provider.connect()

    # ngrok.connect is where pyngrok would download a replacement into the working directory.
    assert ngrok_environment.ngrok.connect.call_count == 1
    if removal == "binary deleted":
        mock_installer.install_ngrok.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []

    if removal == "binary deleted":
        await provider.connect()

        second_path = _started_config(ngrok_environment).ngrok_path
        assert os.path.dirname(second_path) != os.path.dirname(first_path)
        with open(second_path, "rb") as binary_file:
            assert binary_file.read() == ngrok_environment.binary_content

    await provider.disconnect()


@pytest.mark.asyncio
async def test_working_directory_that_is_not_private_is_refused(
    ngrok_environment, temp_root_status, reported_status, monkeypatch
):
    # A /tmp-like parent, so it is the working directory check that refuses.
    temp_root_status(mode=stat.S_IFDIR | 0o1777, uid=0)
    real_stat = os.stat
    # geteuid is patched so the check also runs on Windows, which has no geteuid.
    monkeypatch.setattr(
        os, "geteuid", lambda: real_stat(ngrok_environment.source_binary).st_uid, raising=False
    )
    reported_status(_is_working_directory, permissions=0o755)
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


@pytest.mark.asyncio
async def test_working_directory_owned_by_another_user_is_refused(
    ngrok_environment, temp_root_status, reported_status, monkeypatch
):
    temp_root_status(mode=stat.S_IFDIR | 0o1777, uid=0)
    real_stat = os.stat
    monkeypatch.setattr(
        os,
        "geteuid",
        lambda: real_stat(ngrok_environment.source_binary).st_uid + 1,
        raising=False,
    )
    # Windows reports st_mode 0o777 for directories, so present a private mode there.
    reported_status(_is_working_directory, permissions=0o700)
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


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


@pytest.mark.asyncio
async def test_disconnect_mid_reconnect_cleans_up_when_ngrok_disconnect_fails(
    ngrok_environment, provider_blocked_mid_reconnect
):
    provider, blocking_connect = provider_blocked_mid_reconnect
    ngrok_environment.ngrok.disconnect.side_effect = RuntimeError("ngrok API unreachable")

    disconnect_task = asyncio.create_task(provider.disconnect())
    assert await asyncio.to_thread(blocking_connect.killed.wait, 5)
    blocking_connect.release.set()
    await asyncio.wait_for(disconnect_task, timeout=5)

    assert provider.public_url is None
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
        self.call_count = 0

    def __call__(self, *args, **kwargs):
        self.call_count += 1
        if self.call_count == 1:
            raise RuntimeError("initial connect failed")
        self.started.set()
        assert self.release.wait(timeout=5), "test never released the blocked connect"
        return self.tunnel

    def kill(self, *args):
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

    disconnect_task = asyncio.create_task(provider.disconnect())
    assert await asyncio.to_thread(blocking_connect.killed.wait, 5)
    blocking_connect.release.set()
    await asyncio.wait_for(disconnect_task, timeout=5)

    assert provider.public_url is None
    # The tunnel the late start opened is closed rather than left running.
    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        blocking_connect.tunnel.public_url, pyngrok_config=ANY
    )
    assert list(ngrok_environment.temp_root.iterdir()) == []


@pytest.mark.asyncio
async def test_disconnect_wait_for_hung_start_is_bounded(
    ngrok_environment, provider_blocked_mid_reconnect, monkeypatch
):
    provider, blocking_connect = provider_blocked_mid_reconnect
    monkeypatch.setattr(ngrok_tunnel_module, "START_WAIT_SLACK_SECONDS", 0.2)
    provider._config.startup_timeout = 0
    provider._config.request_timeout = 0
    ngrok_path = _started_config(ngrok_environment).ngrok_path

    await asyncio.wait_for(provider.disconnect(), timeout=3)

    assert not blocking_connect.release.is_set()
    # Killing the process is what ends pyngrok's blocking startup read.
    ngrok_environment.process.kill_process.assert_called_with(ngrok_path)

    # The abandoned start cleans up after itself once it finally returns.
    blocking_connect.release.set()
    await _wait_until(lambda: ngrok_environment.ngrok.disconnect.called)
    await _wait_until(lambda: list(ngrok_environment.temp_root.iterdir()) == [])
    ngrok_environment.ngrok.disconnect.assert_called_once_with(
        blocking_connect.tunnel.public_url, pyngrok_config=ANY
    )
    assert provider.public_url is None


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

    await provider.connect()

    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_called_once()
    with open(_started_config(ngrok_environment).ngrok_path, "rb") as binary_file:
        assert binary_file.read() == ngrok_environment.binary_content

    await provider.disconnect()


@pytest.mark.asyncio
async def test_working_directory_removed_before_placement_recovers_on_next_attempt(
    ngrok_environment, monkeypatch
):
    real_create = ngrok_tunnel_module.create_locked_working_directory
    created_directories = []

    # Stands in for a temp cleaner deleting the directory right after it was created.
    def create_then_lose_first_directory():
        working_directory, lock_descriptor = real_create()
        created_directories.append(working_directory)
        if len(created_directories) == 1:
            shutil.rmtree(working_directory)
        return working_directory, lock_descriptor

    monkeypatch.setattr(
        ngrok_tunnel_module, "create_locked_working_directory", create_then_lose_first_directory
    )
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_called_once()
    ngrok_path = _started_config(ngrok_environment).ngrok_path
    assert os.path.dirname(ngrok_path) == created_directories[1]
    with open(ngrok_path, "rb") as binary_file:
        assert binary_file.read() == ngrok_environment.binary_content

    await provider.disconnect()


@pytest.mark.asyncio
async def test_symlink_failure_that_is_not_lack_of_support_is_not_copied_around(
    ngrok_environment, monkeypatch
):
    def symlink_fails(*args, **kwargs):
        raise OSError(errno.EIO, "Input/output error")

    monkeypatch.setattr(os, "symlink", symlink_fails)
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


@pytest.mark.asyncio
async def test_occupied_binary_path_is_refused_whatever_error_symlink_reports(
    ngrok_environment, tmp_path, monkeypatch
):
    planted_directory = tmp_path / "planted"
    planted_directory.mkdir(mode=0o700)
    (planted_directory / "ngrok").mkdir()
    monkeypatch.setattr(tempfile, "mkdtemp", lambda **kwargs: str(planted_directory))

    # What Windows raises for a directory already at the symlink path.
    def symlink_access_denied(*args, **kwargs):
        raise PermissionError(errno.EACCES, "Access is denied")

    monkeypatch.setattr(os, "symlink", symlink_access_denied)
    provider = _make_provider()

    await provider.connect()
    # The directory is kept, so a second attempt refuses again rather than recovering.
    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert (planted_directory / "ngrok").is_dir()

    await provider.disconnect()
