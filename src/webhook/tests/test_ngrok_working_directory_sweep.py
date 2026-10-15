import asyncio
import errno
import importlib.util
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from loguru import logger

from app.core.settings import settings
from app.main import lifespan
from app.providers.tunnels import ngrok_working_directory as working_directory_module
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel
from app.providers.tunnels.ngrok_working_directory import (
    LOCK_FILE_NAME,
    PENDING_LOCK_FILE_NAME,
    UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS,
    NgrokWorkingDirectoryError,
    remove_stale_working_directories,
)
from app.services.tunnel_registry import TunnelRegistry

REAL_FCNTL = working_directory_module.fcntl

requires_flock = pytest.mark.skipif(
    REAL_FCNTL is None, reason="Needs real flock semantics; fcntl is POSIX-only"
)

# Takes the lock in a separate process, reports it, then holds it until killed.
_LOCK_HOLDER_SCRIPT = """
import fcntl, os, sys
descriptor = os.open(sys.argv[1], os.O_RDWR)
fcntl.flock(descriptor, fcntl.LOCK_EX)
print("locked", flush=True)
sys.stdin.read()
"""


class _FakeFcntl:
    """Stand-in for fcntl on Windows: every lock attempt succeeds unless told otherwise."""

    LOCK_EX = 2
    LOCK_NB = 4

    def __init__(self, flock_error: OSError | None = None):
        self._flock_error = flock_error

    def flock(self, descriptor, operation):
        if self._flock_error is not None:
            raise self._flock_error


@pytest.fixture
def sweep_environment(ngrok_environment, temp_root_status, reported_status, monkeypatch):
    """The temp root the sweep scans. Real flock, owner and mode on POSIX; on Windows a
    succeeding fake flock, a safe temp root and an emulated 0700 mode owned by the current
    user, so the sweep's selection logic runs there too. Windows cannot delete a directory
    whose lock file is still open, so tests removing locked directories need real flock."""
    if REAL_FCNTL is None:
        monkeypatch.setattr(working_directory_module, "fcntl", _FakeFcntl())
        monkeypatch.setattr(os, "geteuid", lambda: 0, raising=False)
        temp_root_status(mode=stat.S_IFDIR | 0o755, uid=0)
        reported_status(lambda path: os.path.basename(path).startswith("ngrok_"), permissions=0o700)

    def set_mode(path, mode):
        if REAL_FCNTL is None:
            target = os.fspath(path)
            reported_status(lambda path: path == target, permissions=mode)
        else:
            os.chmod(path, mode)

    return SimpleNamespace(root=ngrok_environment.temp_root, set_mode=set_mode)


def _make_working_directory(parent, name, with_lock_file=True):
    path = parent / name
    path.mkdir()
    # chmod after mkdir: the process umask may strip bits from mkdir's mode.
    os.chmod(path, 0o700)
    if with_lock_file:
        (path / LOCK_FILE_NAME).touch()
    return path


def _make_unlocked_directory(parent, name, age_seconds):
    path = _make_working_directory(parent, name, with_lock_file=False)
    modified_at = time.time() - age_seconds
    os.utime(path, (modified_at, modified_at))
    return path


def _lock_is_free(lock_path) -> bool:
    """Try the lock through a separate open file description, as another process would."""
    descriptor = os.open(lock_path, os.O_RDWR)
    try:
        REAL_FCNTL.flock(descriptor, REAL_FCNTL.LOCK_EX | REAL_FCNTL.LOCK_NB)
    except BlockingIOError:
        return False
    finally:
        os.close(descriptor)
    return True


@pytest.fixture
def error_logs():
    records = []
    sink_id = logger.add(lambda message: records.append(message.record), level="ERROR")
    yield records
    logger.remove(sink_id)


def _make_provider() -> NgrokTunnel:
    return NgrokTunnel(port=settings.WEBHOOK_PORT, auth_token="test-token")


def _symlinks_supported(directory) -> bool:
    probe = directory / "symlink_probe"
    try:
        os.symlink(directory, probe, target_is_directory=True)
    except OSError:
        return False
    os.remove(probe)
    return True


@requires_flock
def test_orphaned_directory_with_unlocked_lock_file_is_removed(sweep_environment):
    orphan = _make_working_directory(sweep_environment.root, "ngrok_orphan")

    remove_stale_working_directories()

    assert not orphan.exists()


@requires_flock
def test_directory_locked_by_a_live_process_is_kept_until_that_process_is_killed(
    sweep_environment,
):
    working_directory = _make_working_directory(sweep_environment.root, "ngrok_live")
    lock_holder = subprocess.Popen(
        [sys.executable, "-c", _LOCK_HOLDER_SCRIPT, str(working_directory / LOCK_FILE_NAME)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert lock_holder.stdout.readline().strip() == "locked"

        remove_stale_working_directories()

        assert (working_directory / LOCK_FILE_NAME).exists()

        # SIGKILL, like `docker kill`: the kernel releases the lock with the process.
        lock_holder.kill()
        lock_holder.wait(timeout=5)
        remove_stale_working_directories()

        assert not working_directory.exists()
    finally:
        lock_holder.kill()
        lock_holder.wait(timeout=5)
        lock_holder.stdin.close()
        lock_holder.stdout.close()


def test_directory_without_lock_file_is_kept_within_grace_period(sweep_environment):
    young = _make_unlocked_directory(
        sweep_environment.root, "ngrok_young", UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS - 60
    )

    remove_stale_working_directories()

    assert young.is_dir()


def test_directory_without_lock_file_is_removed_after_grace_period(sweep_environment):
    old = _make_unlocked_directory(
        sweep_environment.root, "ngrok_old", UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS + 60
    )

    remove_stale_working_directories()

    assert not old.exists()


def test_directory_owned_by_another_user_is_untouched(sweep_environment, monkeypatch):
    foreign = _make_working_directory(sweep_environment.root, "ngrok_foreign")
    owner_uid = os.lstat(foreign).st_uid
    monkeypatch.setattr(os, "geteuid", lambda: owner_uid + 1, raising=False)

    remove_stale_working_directories()

    assert (foreign / LOCK_FILE_NAME).exists()


@pytest.mark.parametrize("mode", [0o755, 0o750, 0o1700])
def test_directory_that_is_not_mode_0700_is_untouched(sweep_environment, mode):
    shared = _make_working_directory(sweep_environment.root, "ngrok_shared")
    sweep_environment.set_mode(shared, mode)

    remove_stale_working_directories()

    assert (shared / LOCK_FILE_NAME).exists()


def test_regular_file_named_like_a_working_directory_is_untouched(sweep_environment):
    planted_file = sweep_environment.root / "ngrok_file"
    planted_file.write_bytes(b"not a directory")

    remove_stale_working_directories()

    assert planted_file.read_bytes() == b"not a directory"


def test_symlink_named_like_a_working_directory_is_untouched(sweep_environment, tmp_path):
    if not _symlinks_supported(tmp_path):
        pytest.skip("Symlinks unsupported on this platform")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    # The target itself would qualify as an orphan, so only the symlink check protects it.
    target = _make_working_directory(elsewhere, "ngrok_target")
    link = sweep_environment.root / "ngrok_link"
    os.symlink(target, link, target_is_directory=True)

    remove_stale_working_directories()

    assert os.path.islink(link)
    assert (target / LOCK_FILE_NAME).exists()


@requires_flock
def test_directory_whose_lock_file_is_a_symlink_is_untouched(sweep_environment, tmp_path):
    outside_lock = tmp_path / "outside.lock"
    outside_lock.touch()
    working_directory = _make_working_directory(
        sweep_environment.root, "ngrok_linked_lock", with_lock_file=False
    )
    os.symlink(outside_lock, working_directory / LOCK_FILE_NAME)

    remove_stale_working_directories()

    assert os.path.islink(working_directory / LOCK_FILE_NAME)
    assert outside_lock.exists()


def test_lock_error_other_than_would_block_skips_the_directory(sweep_environment, monkeypatch):
    working_directory = _make_working_directory(sweep_environment.root, "ngrok_nolock")

    def flock_unsupported(descriptor, operation):
        raise OSError(errno.ENOLCK, "No locks available")

    monkeypatch.setattr(working_directory_module.fcntl, "flock", flock_unsupported)

    remove_stale_working_directories()

    assert (working_directory / LOCK_FILE_NAME).exists()


@pytest.mark.parametrize(
    "unsafe_mode",
    [stat.S_IFDIR | 0o777, stat.S_IFDIR | 0o775],
    ids=["world-writable", "group-writable"],
)
def test_sweep_removes_nothing_when_the_temp_root_is_not_sticky(
    sweep_environment, temp_root_status, unsafe_mode
):
    orphan = _make_working_directory(sweep_environment.root, "ngrok_orphan")
    old_unlocked = _make_unlocked_directory(
        sweep_environment.root, "ngrok_old", UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS + 60
    )
    temp_root_status(mode=unsafe_mode, uid=os.geteuid())

    remove_stale_working_directories()

    assert (orphan / LOCK_FILE_NAME).exists()
    assert old_unlocked.is_dir()


def _make_old_unlocked_directory(parent, name):
    return _make_unlocked_directory(parent, name, UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS + 60)


def test_failure_on_one_directory_does_not_stop_the_others(sweep_environment, monkeypatch):
    failing = _make_old_unlocked_directory(sweep_environment.root, "ngrok_fails")
    orphans = [
        _make_old_unlocked_directory(sweep_environment.root, name)
        for name in ("ngrok_orphan_a", "ngrok_orphan_z")
    ]
    real_rmtree = shutil.rmtree

    def rmtree_failing_for_one(path, *args, **kwargs):
        if os.path.basename(path) == "ngrok_fails":
            raise PermissionError(errno.EACCES, "Permission denied", path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree_failing_for_one)

    remove_stale_working_directories()

    assert failing.is_dir()
    assert not any(orphan.exists() for orphan in orphans)


def test_directory_removed_by_someone_else_meanwhile_is_not_an_error(
    sweep_environment, monkeypatch, error_logs
):
    vanishing = _make_old_unlocked_directory(sweep_environment.root, "ngrok_vanishing")
    orphan = _make_old_unlocked_directory(sweep_environment.root, "ngrok_orphan")
    real_listdir = os.listdir
    real_rmtree = shutil.rmtree

    # "ngrok_gone" was listed but is gone before lstat; "ngrok_vanishing" goes mid-removal.
    def listdir_with_a_gone_entry(path):
        return [*real_listdir(path), "ngrok_gone"]

    def rmtree_racing_another_remover(path, *args, **kwargs):
        if os.path.basename(path) == "ngrok_vanishing":
            real_rmtree(path)
            raise FileNotFoundError(errno.ENOENT, "No such file or directory", path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(os, "listdir", listdir_with_a_gone_entry)
    monkeypatch.setattr(shutil, "rmtree", rmtree_racing_another_remover)

    remove_stale_working_directories()

    assert not vanishing.exists()
    assert not orphan.exists()
    assert error_logs == []


def test_sweep_does_not_raise_when_the_temp_root_cannot_be_checked(
    sweep_environment, tmp_path, monkeypatch
):
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "missing"))

    remove_stale_working_directories()


@requires_flock
def test_sweep_holds_the_lock_while_removing_so_a_concurrent_sweep_skips(
    sweep_environment, monkeypatch, error_logs
):
    orphan = _make_working_directory(sweep_environment.root, "ngrok_orphan")
    real_rmtree = shutil.rmtree
    observed = {}

    def rmtree_with_a_concurrent_sweep(path, *args, **kwargs):
        if not observed:
            observed["lock_free"] = _lock_is_free(os.path.join(path, LOCK_FILE_NAME))
            remove_stale_working_directories()
            observed["still_there"] = os.path.isdir(path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(shutil, "rmtree", rmtree_with_a_concurrent_sweep)

    remove_stale_working_directories()

    assert observed == {"lock_free": False, "still_there": True}
    assert not orphan.exists()
    assert error_logs == []


def test_unrelated_entries_in_the_temp_root_are_untouched(sweep_environment):
    unrelated = sweep_environment.root / "other_service"
    unrelated.mkdir()
    (unrelated / LOCK_FILE_NAME).touch()

    remove_stale_working_directories()

    assert (unrelated / LOCK_FILE_NAME).exists()


@requires_flock
async def test_tunnel_holds_its_lock_across_reconnects_and_releases_it_on_disconnect(
    ngrok_environment,
):
    provider = _make_provider()
    await provider.connect()
    working_directory = provider._working_directory
    lock_path = os.path.join(working_directory, LOCK_FILE_NAME)
    assert not _lock_is_free(lock_path)

    provider._tunnel = None
    await provider._establish_connection()

    assert ngrok_environment.ngrok.connect.call_count == 2
    assert provider._working_directory == working_directory
    assert not _lock_is_free(lock_path)
    assert not os.path.exists(os.path.join(working_directory, PENDING_LOCK_FILE_NAME))

    # Opened before the removal so the lock can still be tried once the file is unlinked.
    lock_descriptor = os.open(lock_path, os.O_RDWR)
    try:
        await provider.disconnect()

        assert not os.path.exists(working_directory)
        REAL_FCNTL.flock(lock_descriptor, REAL_FCNTL.LOCK_EX | REAL_FCNTL.LOCK_NB)
    finally:
        os.close(lock_descriptor)


@requires_flock
async def test_sweep_before_the_new_lock_file_is_locked_keeps_the_directory(
    ngrok_environment, monkeypatch
):
    swept = []

    # A sweep of another process landing between creating the lock file and locking it.
    def flock_after_a_sweep(descriptor, operation):
        if not swept:
            swept.append(True)
            remove_stale_working_directories()
        return REAL_FCNTL.flock(descriptor, operation)

    monkeypatch.setattr(
        working_directory_module,
        "fcntl",
        SimpleNamespace(
            LOCK_EX=REAL_FCNTL.LOCK_EX, LOCK_NB=REAL_FCNTL.LOCK_NB, flock=flock_after_a_sweep
        ),
    )
    provider = _make_provider()

    await provider.connect()

    assert swept
    ngrok_environment.ngrok.connect.assert_called_once()
    assert not _lock_is_free(os.path.join(provider._working_directory, LOCK_FILE_NAME))

    await provider.disconnect()


@requires_flock
async def test_sweep_keeps_the_directory_of_a_running_tunnel(ngrok_environment):
    provider = _make_provider()
    await provider.connect()
    ngrok_path = ngrok_environment.ngrok.connect.call_args.kwargs["pyngrok_config"].ngrok_path

    remove_stale_working_directories()

    assert os.path.exists(ngrok_path)
    await provider.disconnect()
    assert list(ngrok_environment.temp_root.iterdir()) == []


async def test_tunnel_refuses_to_run_when_its_directory_cannot_be_locked(
    ngrok_environment, monkeypatch
):
    monkeypatch.setattr(
        working_directory_module,
        "fcntl",
        _FakeFcntl(OSError(errno.ENOLCK, "No locks available")),
    )
    provider = _make_provider()
    provider._is_running = True

    with pytest.raises(NgrokWorkingDirectoryError, match="cannot lock"):
        await provider._establish_connection()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert provider._working_directory_lock is None
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


def test_sweep_is_a_no_op_without_fcntl(ngrok_environment, monkeypatch):
    monkeypatch.setattr(working_directory_module, "fcntl", None)
    root = ngrok_environment.temp_root
    orphan = _make_working_directory(root, "ngrok_orphan")
    old_unlocked = _make_unlocked_directory(
        root, "ngrok_old", UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS + 60
    )

    remove_stale_working_directories()

    assert (orphan / LOCK_FILE_NAME).exists()
    assert old_unlocked.is_dir()


async def test_tunnel_runs_without_a_lock_when_fcntl_is_unavailable(ngrok_environment, monkeypatch):
    monkeypatch.setattr(working_directory_module, "fcntl", None)
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_called_once()
    assert provider._working_directory_lock is None
    assert not os.path.exists(os.path.join(provider._working_directory, LOCK_FILE_NAME))

    await provider.disconnect()
    assert list(ngrok_environment.temp_root.iterdir()) == []


def test_module_imports_when_fcntl_is_missing(monkeypatch):
    # None in sys.modules makes `import fcntl` raise ImportError, as on Windows.
    monkeypatch.setitem(sys.modules, "fcntl", None)
    spec = importlib.util.spec_from_file_location(
        "ngrok_working_directory_without_fcntl", working_directory_module.__file__
    )
    module = importlib.util.module_from_spec(spec)

    spec.loader.exec_module(module)

    assert module.fcntl is None
    module.remove_stale_working_directories()


async def _enter_lifespan(while_running=None):
    with patch("app.main.get_tunnel_registry", return_value=TunnelRegistry()):
        async with lifespan(MagicMock()):
            if while_running is not None:
                await while_running()


class _RecordingListener:
    """listen_redis stand-in that records when the listener, the only registrar, starts."""

    def __init__(self, events: list[str]):
        self.events = events
        self.started = asyncio.Event()
        self.started_for_threads = threading.Event()

    async def __call__(self, redis_service, tunnel_registry):
        self.events.append("listener")
        self.started.set()
        self.started_for_threads.set()

    async def wait_started(self):
        await asyncio.wait_for(self.started.wait(), timeout=3)


async def test_startup_sweeps_before_the_listener_can_register_tunnels(lifespan_dependencies):
    events: list[str] = []
    listener = _RecordingListener(events)

    # Gives a listener started too early the chance to run first; returns at once if it does.
    def sweep_waiting_for_an_early_listener():
        listener.started_for_threads.wait(timeout=0.5)
        events.append("sweep")

    with (
        patch(
            "app.main.remove_stale_working_directories",
            side_effect=sweep_waiting_for_an_early_listener,
        ),
        patch("app.main.listen_redis", new=listener),
    ):
        await _enter_lifespan(while_running=listener.wait_started)

    assert events == ["sweep", "listener"]


async def test_startup_continues_when_the_sweep_raises(lifespan_dependencies):
    events: list[str] = []
    listener = _RecordingListener(events)

    with (
        patch(
            "app.main.remove_stale_working_directories",
            side_effect=RuntimeError("sweep failed"),
        ),
        patch("app.main.listen_redis", new=listener),
    ):
        await _enter_lifespan(while_running=listener.wait_started)

    assert events == ["listener"]
    lifespan_dependencies.assert_awaited_once()


@requires_flock
async def test_startup_removes_a_killed_run_directory_and_keeps_the_rest(
    sweep_environment, lifespan_dependencies
):
    orphan = _make_working_directory(sweep_environment.root, "ngrok_killed_run")
    young = _make_unlocked_directory(sweep_environment.root, "ngrok_just_created", 0)
    sweep_results = {}

    async def record_directories():
        sweep_results["orphan"] = orphan.exists()
        sweep_results["young"] = young.is_dir()

    with patch("app.main.remove_stale_working_directories", new=remove_stale_working_directories):
        await _enter_lifespan(while_running=record_directories)

    assert sweep_results == {"orphan": False, "young": True}
