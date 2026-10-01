import os
import stat
import tempfile

import pytest

from app.core.settings import settings
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel
from app.providers.tunnels.ngrok_working_directory import (
    NgrokWorkingDirectoryError,
    create_locked_working_directory,
    remove_working_directory,
    temp_root_unsafe_reason,
)

# Patched rather than real, so the owner cases run the same as root, as a user and on
# Windows, which has no geteuid.
CURRENT_UID = 1000
OTHER_UID = 1001
ROOT_UID = 0


@pytest.fixture
def as_current_user(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: CURRENT_UID, raising=False)


def _make_provider() -> NgrokTunnel:
    provider = NgrokTunnel(port=settings.WEBHOOK_PORT, auth_token="test-token")
    provider._is_running = True
    return provider


@pytest.mark.parametrize(
    ("mode", "owner_uid", "reason"),
    [
        (stat.S_IFDIR | 0o777, CURRENT_UID, "writable by other users without the sticky bit"),
        (stat.S_IFDIR | 0o777, ROOT_UID, "writable by other users without the sticky bit"),
        (stat.S_IFDIR | 0o775, ROOT_UID, "writable by other users without the sticky bit"),
        (stat.S_IFDIR | 0o757, CURRENT_UID, "writable by other users without the sticky bit"),
        (stat.S_IFDIR | 0o755, OTHER_UID, "is owned by another user"),
        (stat.S_IFDIR | 0o1777, OTHER_UID, "is owned by another user"),
        (stat.S_IFREG | 0o755, CURRENT_UID, "is not a directory"),
    ],
    ids=[
        "world-writable-not-sticky",
        "root-owned-world-writable-not-sticky",
        "root-owned-group-writable-not-sticky",
        "other-writable-only-not-sticky",
        "owned-by-another-user",
        "owned-by-another-user-even-if-sticky",
        "not-a-directory",
    ],
)
async def test_unsafe_temp_root_is_refused_before_anything_is_created(
    ngrok_environment, temp_root_status, as_current_user, mode, owner_uid, reason
):
    temp_root_status(mode=mode, uid=owner_uid)
    provider = _make_provider()

    with pytest.raises(NgrokWorkingDirectoryError, match=reason):
        await provider._establish_connection()

    ngrok_environment.ngrok.connect.assert_not_called()
    assert provider._working_directory is None
    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


@pytest.mark.parametrize(
    ("mode", "owner_uid"),
    [
        (stat.S_IFDIR | 0o1777, ROOT_UID),
        (stat.S_IFDIR | 0o1770, ROOT_UID),
        (stat.S_IFDIR | 0o1777, CURRENT_UID),
        (stat.S_IFDIR | 0o755, ROOT_UID),
        (stat.S_IFDIR | 0o755, CURRENT_UID),
        (stat.S_IFDIR | 0o700, CURRENT_UID),
    ],
    ids=[
        "root-owned-sticky-world-writable-like-tmp",
        "root-owned-sticky-group-writable",
        "own-sticky-world-writable",
        "root-owned-not-writable-by-others",
        "own-not-writable-by-others",
        "own-private",
    ],
)
def test_safe_temp_root_is_accepted(
    ngrok_environment, temp_root_status, as_current_user, mode, owner_uid
):
    temp_root_status(mode=mode, uid=owner_uid)

    assert temp_root_unsafe_reason(os.path.realpath(ngrok_environment.temp_root)) is None


async def test_resolved_temp_root_is_checked_and_used(
    ngrok_environment, temp_root_status, reported_status, as_current_user, tmp_path, monkeypatch
):
    # Portable stand-in for a symlinked TMPDIR: the alias itself does not exist.
    alias = str(tmp_path / "tmpdir-alias")
    resolved_temp_root = os.path.realpath(ngrok_environment.temp_root)
    real_realpath = os.path.realpath
    monkeypatch.setattr(
        os.path,
        "realpath",
        lambda path, *args, **kwargs: (
            resolved_temp_root if os.fspath(path) == alias else real_realpath(path, *args, **kwargs)
        ),
    )
    monkeypatch.setattr(tempfile, "tempdir", alias)
    temp_root_status(mode=stat.S_IFDIR | 0o777, uid=CURRENT_UID)
    provider = _make_provider()

    with pytest.raises(NgrokWorkingDirectoryError, match="without the sticky bit") as refusal:
        await provider._establish_connection()

    assert resolved_temp_root in str(refusal.value)
    assert alias not in str(refusal.value)

    await provider.disconnect()

    # Now a safe root, with the new directory owned by and private to the current user.
    temp_root_status(mode=stat.S_IFDIR | 0o1777, uid=ROOT_UID)
    reported_status(
        lambda path: os.path.basename(path).startswith("ngrok_"),
        permissions=0o700,
        uid=CURRENT_UID,
    )

    working_directory, lock_descriptor = create_locked_working_directory()
    try:
        assert os.path.dirname(working_directory) == resolved_temp_root
    finally:
        remove_working_directory(working_directory, lock_descriptor)


async def test_symlinked_temp_root_is_checked_at_its_target(
    ngrok_environment, temp_root_status, as_current_user, tmp_path, monkeypatch
):
    link = tmp_path / "tmpdir-link"
    try:
        os.symlink(ngrok_environment.temp_root, link, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks unsupported on this platform")
    monkeypatch.setattr(tempfile, "tempdir", str(link))
    # Only the resolved target reports an unsafe mode; the link path is never consulted.
    temp_root_status(mode=stat.S_IFDIR | 0o777, uid=CURRENT_UID)
    provider = _make_provider()

    with pytest.raises(NgrokWorkingDirectoryError, match="without the sticky bit"):
        await provider._establish_connection()

    assert list(ngrok_environment.temp_root.iterdir()) == []

    await provider.disconnect()


async def test_temp_root_check_is_skipped_without_geteuid(
    ngrok_environment, temp_root_status, monkeypatch
):
    monkeypatch.delattr(os, "geteuid", raising=False)
    temp_root_status(mode=stat.S_IFDIR | 0o777, uid=OTHER_UID)
    provider = _make_provider()

    await provider._establish_connection()

    ngrok_environment.ngrok.connect.assert_called_once()

    await provider.disconnect()
