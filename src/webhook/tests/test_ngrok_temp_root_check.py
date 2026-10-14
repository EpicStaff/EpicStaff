import os
import stat
import tempfile

import pytest

from app.core.settings import settings
from app.providers.tunnels.ngrok_tunnel import NgrokTunnel
from app.providers.tunnels.ngrok_working_directory import temp_root_unsafe_reason

# Patched rather than real, so the owner cases run the same as root, as a user and on
# Windows, which has no geteuid.
CURRENT_UID = 1000
OTHER_UID = 1001
ROOT_UID = 0


@pytest.fixture
def as_current_user(monkeypatch):
    monkeypatch.setattr(os, "geteuid", lambda: CURRENT_UID, raising=False)


def _make_provider() -> NgrokTunnel:
    return NgrokTunnel(port=settings.WEBHOOK_PORT, auth_token="test-token")


@pytest.mark.parametrize(
    ("mode", "owner_uid", "reason"),
    [
        (stat.S_IFDIR | 0o777, CURRENT_UID, "is writable by other users without the sticky bit"),
        (stat.S_IFDIR | 0o777, ROOT_UID, "is writable by other users without the sticky bit"),
        (stat.S_IFDIR | 0o775, ROOT_UID, "is writable by other users without the sticky bit"),
        (stat.S_IFDIR | 0o757, CURRENT_UID, "is writable by other users without the sticky bit"),
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
def test_unsafe_temp_root_is_reported(
    ngrok_environment, temp_root_status, as_current_user, mode, owner_uid, reason
):
    temp_root_status(mode=mode, uid=owner_uid)

    assert temp_root_unsafe_reason(os.path.realpath(ngrok_environment.temp_root)) == reason


async def test_tunnel_creates_nothing_and_never_starts_in_an_unsafe_temp_root(
    ngrok_environment, temp_root_status, as_current_user
):
    temp_root_status(mode=stat.S_IFDIR | 0o777, uid=CURRENT_UID)
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()
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

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_not_called()

    # Once the target is safe, the working directory is created in the target itself.
    temp_root_status(mode=stat.S_IFDIR | 0o1777, uid=ROOT_UID)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(ngrok_environment.source_binary).st_uid)

    await provider.connect()

    started_path = ngrok_environment.ngrok.connect.call_args.kwargs["pyngrok_config"].ngrok_path
    assert os.path.dirname(os.path.dirname(started_path)) == os.path.realpath(
        ngrok_environment.temp_root
    )

    await provider.disconnect()


async def test_temp_root_check_is_skipped_without_geteuid(
    ngrok_environment, temp_root_status, monkeypatch
):
    monkeypatch.delattr(os, "geteuid", raising=False)
    temp_root_status(mode=stat.S_IFDIR | 0o777, uid=OTHER_UID)
    provider = _make_provider()

    await provider.connect()

    ngrok_environment.ngrok.connect.assert_called_once()

    await provider.disconnect()
