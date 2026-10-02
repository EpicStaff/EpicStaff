"""Lifecycle of the private per-tunnel ngrok working directories: creation, locking, removal
and the startup sweep of directories left behind by processes that died."""

import os
import shutil
import stat
import tempfile
import time

from loguru import logger

try:
    import fcntl
except ImportError:
    # Windows: no flock, so working directories are neither locked nor swept.
    fcntl = None

WORKING_DIRECTORY_PREFIX = "ngrok_"
LOCK_FILE_NAME = "ngrok.lock"
# The lock is taken under this name and only then renamed to LOCK_FILE_NAME, so the sweep
# never finds a lock file that nobody holds yet.
PENDING_LOCK_FILE_NAME = "ngrok.lock.new"
# A working directory without a lock file is either being created right now or was left by a
# process that died before locking it, or by a version that did not lock; its age tells
# them apart.
UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS = 300


class NgrokWorkingDirectoryError(RuntimeError):
    """Raised when the private ngrok working directory or the binary in it is unusable."""


def temp_root_unsafe_reason(temp_root: str) -> str | None:
    """Return why other users could replace entries in `temp_root`, or None if they cannot.

    A private 0700 working directory is only as safe as its parent: where another user may
    write without the sticky bit, they can rename our directory away after it is checked and
    put their own under the same name. The owner must be this user or root, since the owner
    can always do that. Always None on Windows.

    Only `temp_root` itself is checked, not the directories above it: this assumes it sits
    under a path other users cannot write to, as /tmp does. A TMPDIR below a directory that
    another user can write to is not covered.

    Raises:
        OSError: `temp_root` cannot be stat-ed.
    """
    # No geteuid means Windows, where os.stat reports no meaningful POSIX mode or owner.
    if not hasattr(os, "geteuid"):
        return None
    root_status = os.stat(temp_root)
    if not stat.S_ISDIR(root_status.st_mode):
        return "is not a directory"
    if root_status.st_uid not in (os.geteuid(), 0):
        return "is owned by another user"
    writable_by_others = root_status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    if writable_by_others and not root_status.st_mode & stat.S_ISVTX:
        return "is writable by other users without the sticky bit"
    return None


def create_locked_working_directory() -> tuple[str, int | None]:
    """Create a private (0700 on POSIX) working directory in a safe temp directory, locked.

    Nothing is left behind when this raises.

    Returns:
        The directory, and the descriptor holding its lock (None where flock is
        unavailable). Keep the descriptor open for the directory's whole life: the held lock
        is what tells the startup sweep the directory is live.

    Raises:
        NgrokWorkingDirectoryError: The temp directory lets other users replace entries, or
            the new directory is not private or cannot be locked.
    """
    # Resolved first so the directory checked is the one mkdtemp writes into, even when the
    # temp directory is reached through a symlink.
    temp_root = os.path.realpath(tempfile.gettempdir())
    unsafe_reason = temp_root_unsafe_reason(temp_root)
    if unsafe_reason is not None:
        raise NgrokWorkingDirectoryError(
            f"Refusing to run ngrok: temp directory {temp_root} {unsafe_reason}."
        )

    working_directory = tempfile.mkdtemp(prefix=WORKING_DIRECTORY_PREFIX, dir=temp_root)
    try:
        _require_private(working_directory)
        lock_descriptor = _lock(working_directory)
    except BaseException:
        shutil.rmtree(working_directory, ignore_errors=True)
        raise
    return working_directory, lock_descriptor


def remove_working_directory(working_directory: str | None, lock_descriptor: int | None) -> None:
    """Release the directory's lock, then delete the directory, ignoring errors."""
    if lock_descriptor is not None:
        os.close(lock_descriptor)
    if working_directory is not None:
        shutil.rmtree(working_directory, ignore_errors=True)


def _require_private(working_directory: str) -> None:
    if not hasattr(os, "geteuid"):
        return
    directory_status = os.stat(working_directory)
    is_private = (
        stat.S_IMODE(directory_status.st_mode) == 0o700 and directory_status.st_uid == os.geteuid()
    )
    if not is_private:
        raise NgrokWorkingDirectoryError(
            f"Refusing to run ngrok: {working_directory} is not a private 0700 directory."
        )


def _lock(working_directory: str) -> int | None:
    if fcntl is None:
        return None
    pending_lock_path = os.path.join(working_directory, PENDING_LOCK_FILE_NAME)
    lock_flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    lock_descriptor = None
    try:
        lock_descriptor = os.open(pending_lock_path, lock_flags, 0o600)
        fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # The lock belongs to the open file description, so it survives the rename.
        os.rename(pending_lock_path, os.path.join(working_directory, LOCK_FILE_NAME))
    except OSError as error:
        # Fail closed: an unlocked directory looks abandoned to the startup sweep of
        # another process sharing this temp directory.
        if lock_descriptor is not None:
            os.close(lock_descriptor)
        raise NgrokWorkingDirectoryError(
            f"Refusing to run ngrok: cannot lock {working_directory}: {error}"
        ) from error
    return lock_descriptor


def remove_stale_working_directories() -> None:
    """Remove ngrok working directories whose owning process has died.

    Meant to run once at service startup, before any tunnel connects. A tunnel holds an
    exclusive flock on the lock file in its directory for the directory's whole life, and
    the kernel releases it when the process dies, even by SIGKILL. A directory is removed
    only when it is a real directory owned by this user with mode 0700 and its lock can be
    taken, or it has no lock file and is older than the grace period. Anything else,
    including a lock that cannot be tried, is left alone. Does nothing where flock is
    unavailable, or where the temp directory cannot be checked or lets other users replace
    entries in it. Never raises an Exception; failures are logged per directory.
    """
    if fcntl is None:
        return
    temp_root = os.path.realpath(tempfile.gettempdir())
    try:
        unsafe_reason = temp_root_unsafe_reason(temp_root)
    except OSError as error:
        logger.warning("Not sweeping stale ngrok directories: cannot stat {}: {}", temp_root, error)
        return
    if unsafe_reason is not None:
        logger.warning(
            "Not sweeping stale ngrok directories: temp directory {} {}.", temp_root, unsafe_reason
        )
        return
    try:
        entry_names = os.listdir(temp_root)
    except OSError as error:
        logger.warning("Not sweeping stale ngrok directories: cannot list {}: {}", temp_root, error)
        return

    for entry_name in entry_names:
        if not entry_name.startswith(WORKING_DIRECTORY_PREFIX):
            continue
        path = os.path.join(temp_root, entry_name)
        try:
            _remove_if_stale(path)
        except FileNotFoundError:
            logger.debug("ngrok working directory {} was already removed.", path)
        except Exception:
            logger.exception("Failed to sweep stale ngrok working directory {}", path)


def _remove_if_stale(path: str) -> None:
    directory_status = os.lstat(path)
    is_our_private_directory = (
        stat.S_ISDIR(directory_status.st_mode)
        and directory_status.st_uid == os.geteuid()
        and stat.S_IMODE(directory_status.st_mode) == 0o700
    )
    if not is_our_private_directory:
        return

    lock_flags = os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    try:
        lock_descriptor = os.open(os.path.join(path, LOCK_FILE_NAME), lock_flags)
    except FileNotFoundError:
        age_seconds = time.time() - directory_status.st_mtime
        if age_seconds > UNLOCKED_WORKING_DIRECTORY_GRACE_SECONDS:
            logger.info("Removing unlocked stale ngrok working directory {}", path)
            shutil.rmtree(path)
        return
    except OSError as error:
        logger.debug("Skipping ngrok working directory {}: cannot open its lock: {}", path, error)
        return

    # Held until the directory is gone, so a concurrent sweep finds it locked and skips it.
    try:
        try:
            fcntl.flock(lock_descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return
        except OSError as error:
            logger.debug("Skipping ngrok working directory {}: cannot lock it: {}", path, error)
            return
        logger.info("Removing ngrok working directory {} left by a dead process", path)
        shutil.rmtree(path)
    finally:
        os.close(lock_descriptor)
