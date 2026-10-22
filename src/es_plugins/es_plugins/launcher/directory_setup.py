"""Create and repair the node's directories, install plugin code, purge and remove plugin data.

The launcher runs as root with `CHOWN`, `SETUID` and `SETGID` only. Two rules follow:

- It may `chmod` only a path it owns (no `CAP_FOWNER`), and it cannot even open a
  directory another UID keeps private (no `CAP_DAC_OVERRIDE`). Every directory is
  therefore set up by: take ownership (`lchown` to the launcher), `chmod`, open, then hand
  it to its owner. This also makes setup idempotent on an existing volume, whatever owners
  and modes a previous run or a plugin left behind.
- Deleting a plugin's HOME happens in a helper running as the plugin's UID: root cannot
  enter the plugin's directories.

Entries are taken by name inside a parent that only root may change at that moment, and
are never followed when they are symbolic links: a link a plugin or the agent plants is
refused or replaced, not followed by root.
"""

import errno
import os
import shutil
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from es_plugins.descriptors import write_all
from es_plugins.launcher.kill_by_uid import run_as_user
from es_plugins.layout import (
    AGENT_GID,
    AGENT_UID,
    HEARTBEAT_FILE_NAME,
    NodeLayout,
    check_plugin_identifier,
    check_version_segment,
)

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_CODE_FILES = 20_000
MAX_CODE_BYTES = 1024 * 1024 * 1024
MAX_CODE_DEPTH = 64
_COPY_CHUNK_BYTES = 1024 * 1024


class DirectorySetupError(Exception):
    """A directory or file is not what the node expects; the message names it."""


@dataclass(frozen=True)
class Ownership:
    uid: int
    gid: int


class DirectorySetup:
    """The launcher's filesystem operations.

    The launcher's and the agent's IDs are parameters so that the operations can be tested
    without root, with every owner set to the test's own UID.
    """

    def __init__(
        self,
        layout: NodeLayout,
        *,
        launcher: Ownership = Ownership(0, 0),
        agent: Ownership = Ownership(AGENT_UID, AGENT_GID),
        plugin_gid: int | None = None,
    ):
        """`plugin_gid` None is the node's rule, each plugin's gid equals its uid; a test that
        runs without root passes its own gid instead."""
        self._layout = layout
        self._launcher = launcher
        self._agent = agent
        self._plugin_gid = plugin_gid

    def prepare_tree(self) -> None:
        """Create or repair the node-wide directories, the heartbeat file and the egress policy root."""
        layout = self._layout
        launcher = self._launcher
        for path, mode, owner in (
            (layout.data_root, 0o755, launcher),
            # Group 0: the launcher reads what the agent unpacks here; plugins cannot.
            (layout.agent_directory, 0o750, Ownership(self._agent.uid, launcher.gid)),
            (layout.plugin_data_root, 0o711, launcher),
            (layout.plugins_root, 0o711, launcher),
            (layout.venvs_root, 0o711, launcher),
            (layout.logs_root, 0o700, self._agent),
            # Backups hold every organization's plugin data: the agent's alone.
            (layout.backups_root, 0o700, self._agent),
            (layout.run_root, 0o711, launcher),
            (layout.launcher_socket_directory, 0o750, Ownership(launcher.uid, self._agent.gid)),
        ):
            self._ensure_directory(path, mode, owner)
        with self._open_trusted(layout.run_root) as run_root:
            self._ensure_file(run_root, HEARTBEAT_FILE_NAME, 0o644, self._agent)
        # The egress policy volume's root, when it is mounted. Its parent is the image's (on a
        # read-only root), so nothing is created there: without the volume the agent refuses to
        # start, naming the directory.
        if layout.egress_policy_directory.is_dir():
            self._ensure_directory(layout.egress_policy_directory, 0o755, self._agent)

    def prepare_plugin(self, plugin: str, uid: int) -> None:
        """Create or repair one plugin's directories (see `es_plugins.layout`).

        A directory already a directory with the expected owner and mode is left untouched, so
        preparing a running plugin again (e.g. before a credentials-only runtime-file rewrite)
        never takes its HOME back to root and locks the process out of it.
        """
        layout = self._layout
        gid = uid if self._plugin_gid is None else self._plugin_gid
        plugin_owner = Ownership(uid, gid)
        home = layout.plugin_home(plugin)
        temporary = layout.plugin_temporary_directory(plugin)
        if not (
            self._matches(home, 0o700, plugin_owner)
            and self._matches(temporary, 0o700, plugin_owner)
        ):
            with self._directory(home) as home_descriptor:
                # HOME stays root's while TMPDIR is fixed inside it, so nothing of the plugin
                # can change the entry in between; only then does HOME go back to the plugin.
                with self._take(home_descriptor, "tmp", replace_non_directory=True) as temporary_fd:
                    self._hand_over(temporary_fd, 0o700, plugin_owner)
                self._hand_over(home_descriptor, 0o700, plugin_owner)
        for path, mode, owner in (
            (layout.plugin_code_root(plugin), 0o750, Ownership(self._launcher.uid, gid)),
            (layout.plugin_venvs(plugin), 0o750, Ownership(self._agent.uid, gid)),
            (layout.plugin_run_directory(plugin), 0o711, self._launcher),
        ):
            self._ensure_directory(path, mode, owner)

    def install_code(self, plugin: str, version: str) -> None:
        """Copy the agent's unpacked `backend/src` to `plugins/<id>/<version>/backend/src`.

        The copy is owned by root (files 0644, directories 0755), so the plugin can read its
        code but not change it, and the agent cannot change it afterwards. The source is
        opened one component at a time below `agent/` and only regular files and
        directories are copied, so a link in the agent's tree cannot point root elsewhere.
        `prepare_plugin` must have run first.

        Raises:
            DirectorySetupError: The source holds something other than files and
                directories, or is larger than the caps.
        """
        check_plugin_identifier(plugin)
        check_version_segment(version)
        staging_name = f".install-{version}"
        replaced_name = f".replaced-{version}"
        source_parts = ("unpack", plugin, version, "backend", "src")
        with self._open_trusted(self._layout.plugin_code_root(plugin)) as code_root:
            for leftover in (staging_name, replaced_name):
                _remove_tree_if_present(code_root, leftover)
            with (
                self._new_directory(code_root, staging_name) as staging,
                self._new_directory(staging, "backend") as backend,
                self._new_directory(backend, "src") as destination,
                self._open_below(self._layout.agent_directory, source_parts) as source,
            ):
                _TreeCopy("/".join(source_parts)).copy(source, destination, depth=0)
            if _exists(code_root, version):
                os.rename(version, replaced_name, src_dir_fd=code_root, dst_dir_fd=code_root)
            os.rename(staging_name, version, src_dir_fd=code_root, dst_dir_fd=code_root)
            _remove_tree_if_present(code_root, replaced_name)

    def prune_code(self, plugin: str, keep_version: str) -> list[str]:
        """Delete every entry of `plugins/<id>/` but `keep_version`; return the names deleted.

        After an upgrade completes, is cancelled or is replaced, only the version the plugin runs
        stays. Each entry is taken by name in the root-owned directory, and a link is deleted,
        never followed. A missing directory is fine.
        """
        check_plugin_identifier(plugin)
        check_version_segment(keep_version)
        code_root = self._layout.plugin_code_root(plugin)
        try:
            descriptor = os.open(code_root, _DIRECTORY_FLAGS)
        except FileNotFoundError:
            return []
        try:
            removed = sorted(name for name in os.listdir(descriptor) if name != keep_version)
            for name in removed:
                _remove_tree_if_present(descriptor, name)
        finally:
            os.close(descriptor)
        return removed

    def purge_plugin_data(self, plugin: str, uid: int) -> None:
        """Delete the plugin's HOME. The caller kills the UID's processes first.

        Raises:
            DirectorySetupError: The helper running as the plugin's UID could not empty it.
        """
        home = self._layout.plugin_home(plugin)
        with self._open_trusted(home.parent) as data_root:
            if not _exists(data_root, home.name):
                return
            if not run_as_user(uid, lambda: _remove_contents(home)):
                raise DirectorySetupError(f"{home} could not be emptied as UID {uid}")
            os.rmdir(home.name, dir_fd=data_root)

    def remove_plugin_trees(self, plugin: str) -> None:
        """Delete the plugin's code (`plugins/<id>/`) and run directory, and its empty venvs root.

        Each is taken by name in its root-owned parent; a link in its place is deleted, never
        followed, and a missing one is fine. HOME goes first (`purge_plugin_data`); the agent
        empties `venvs/<id>/`, which it owns.

        Raises:
            DirectorySetupError: `venvs/<id>/` still holds something.
        """
        layout = self._layout
        for tree in (layout.plugin_code_root(plugin), layout.plugin_run_directory(plugin)):
            with self._open_trusted(tree.parent) as parent:
                _remove_tree_if_present(parent, tree.name)
        venvs = layout.plugin_venvs(plugin)
        with self._open_trusted(venvs.parent) as parent:
            entry = _lstat(parent, venvs.name)
            if entry is None:
                return
            if not stat.S_ISDIR(entry.st_mode):
                os.unlink(venvs.name, dir_fd=parent)
                return
            try:
                os.rmdir(venvs.name, dir_fd=parent)
            except OSError as error:
                if error.errno == errno.ENOTEMPTY:
                    raise DirectorySetupError(
                        f"{venvs} is not empty; the agent empties it before the launcher removes it"
                    ) from None
                raise

    def _ensure_directory(self, path: Path, mode: int, owner: Ownership) -> None:
        """Make `path` a directory owned by `owner` with `mode`, repairing it only if needed."""
        if self._matches(path, mode, owner):
            return
        with self._directory(path) as descriptor:
            self._hand_over(descriptor, mode, owner)

    def _matches(self, path: Path, mode: int, owner: Ownership) -> bool:
        """Whether `path` is already a directory owned by `owner` with exactly `mode`."""
        try:
            descriptor = os.open(path, _DIRECTORY_FLAGS)
        except OSError:
            return False
        try:
            info = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        return (
            stat.S_ISDIR(info.st_mode)
            and stat.S_IMODE(info.st_mode) == mode
            and info.st_uid == owner.uid
            and info.st_gid == owner.gid
        )

    def _hand_over(self, descriptor: int, mode: int, owner: Ownership) -> None:
        """Set the final mode while the launcher owns the entry, then give it to `owner`."""
        os.fchmod(descriptor, mode)
        if owner != self._launcher:
            os.fchown(descriptor, owner.uid, owner.gid)

    @contextmanager
    def _directory(self, path: Path) -> Iterator[int]:
        """Take `path` (see `_take`); its parent is a directory only root may change."""
        with self._open_trusted(path.parent) as parent, self._take(parent, path.name) as taken:
            yield taken

    @contextmanager
    def _take(
        self, parent: int, name: str, *, replace_non_directory: bool = False
    ) -> Iterator[int]:
        """Create `parent/name` or take over the existing directory, and open it.

        The entry ends up owned by the launcher with mode 0700, whoever owned it before. A
        link or file of that name is refused, or deleted when `replace_non_directory`.
        """
        entry = _lstat(parent, name)
        if entry is not None and not stat.S_ISDIR(entry.st_mode):
            if not replace_non_directory:
                raise DirectorySetupError(f"{name} exists and is not a directory")
            os.unlink(name, dir_fd=parent)
            entry = None
        if entry is None:
            os.mkdir(name, 0o700, dir_fd=parent)
        os.chown(name, self._launcher.uid, self._launcher.gid, dir_fd=parent, follow_symlinks=False)
        # The parent is the launcher's (or a test's) own directory, so the entry checked as a
        # directory above is still the one changed here.
        os.chmod(name, 0o700, dir_fd=parent)
        with _open_directory(name, parent) as descriptor:
            yield descriptor

    @contextmanager
    def _new_directory(self, parent: int, name: str) -> Iterator[int]:
        os.mkdir(name, 0o700, dir_fd=parent)
        with _open_directory(name, parent) as descriptor:
            os.fchmod(descriptor, 0o755)
            yield descriptor

    @staticmethod
    @contextmanager
    def _open_trusted(path: Path) -> Iterator[int]:
        """Open a directory whose path only root controls (links in it are system ones)."""
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        except OSError as error:
            raise DirectorySetupError(f"{path} cannot be opened: {error}") from None
        try:
            yield descriptor
        finally:
            os.close(descriptor)

    @contextmanager
    def _open_below(self, base: Path, parts: tuple[str, ...]) -> Iterator[int]:
        """Open `base/parts...` refusing a symbolic link at every component below `base`."""
        with self._open_trusted(base) as current:
            descriptors = [current]
            try:
                for part in parts:
                    descriptors.append(os.open(part, _DIRECTORY_FLAGS, dir_fd=descriptors[-1]))
            except OSError as error:
                raise DirectorySetupError(
                    f"{base}/{'/'.join(parts)} is not a plain directory: {error}"
                ) from None
            else:
                yield descriptors[-1]
            finally:
                for descriptor in descriptors[1:]:
                    os.close(descriptor)

    def _ensure_file(self, parent: int, name: str, mode: int, owner: Ownership) -> None:
        entry = _lstat(parent, name)
        if entry is not None:
            if not stat.S_ISREG(entry.st_mode):
                raise DirectorySetupError(f"{name} exists and is not a regular file")
            os.chown(
                name, self._launcher.uid, self._launcher.gid, dir_fd=parent, follow_symlinks=False
            )
            os.chmod(name, 0o600, dir_fd=parent)
        flags = os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
        descriptor = os.open(name, flags, 0o600, dir_fd=parent)
        try:
            self._hand_over(descriptor, mode, owner)
        finally:
            os.close(descriptor)


class _TreeCopy:
    """A copy of a directory tree the agent controls, made by root without following links."""

    def __init__(self, source_label: str):
        self._source_label = source_label
        self._files = 0
        self._bytes = 0

    def copy(self, source: int, destination: int, depth: int) -> None:
        if depth > MAX_CODE_DEPTH:
            raise DirectorySetupError(
                f"{self._source_label} is nested deeper than {MAX_CODE_DEPTH}"
            )
        for name in sorted(os.listdir(source)):
            entry = os.lstat(name, dir_fd=source)
            if stat.S_ISDIR(entry.st_mode):
                os.mkdir(name, 0o700, dir_fd=destination)
                with (
                    _open_directory(name, source) as child_source,
                    _open_directory(name, destination) as child_destination,
                ):
                    os.fchmod(child_destination, 0o755)
                    self.copy(child_source, child_destination, depth + 1)
            elif stat.S_ISREG(entry.st_mode):
                self._copy_file(name, source, destination)
            else:
                raise DirectorySetupError(
                    f"{self._source_label}: {name} is neither a regular file nor a directory"
                )

    def _copy_file(self, name: str, source: int, destination: int) -> None:
        self._files += 1
        if self._files > MAX_CODE_FILES:
            raise DirectorySetupError(
                f"{self._source_label} holds more than {MAX_CODE_FILES} files"
            )
        # O_NONBLOCK: a FIFO the agent planted among the source files returns at once instead
        # of blocking the launcher (PID 1) forever; the fstat below then rejects it. A regular
        # file ignores the flag, so the flag is cleared once it is confirmed regular.
        reader = os.open(
            name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=source
        )
        try:
            # Checked on the open descriptor: the entry may have been swapped since lstat.
            if not stat.S_ISREG(os.fstat(reader).st_mode):
                raise DirectorySetupError(f"{self._source_label}: {name} is not a regular file")
            os.set_blocking(reader, True)
            writer = os.open(
                name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=destination,
            )
            try:
                os.fchmod(writer, 0o644)
                while chunk := os.read(reader, _COPY_CHUNK_BYTES):
                    self._bytes += len(chunk)
                    if self._bytes > MAX_CODE_BYTES:
                        raise DirectorySetupError(
                            f"{self._source_label} holds more than {MAX_CODE_BYTES} bytes"
                        )
                    write_all(writer, chunk)
            finally:
                os.close(writer)
        finally:
            os.close(reader)


@contextmanager
def _open_directory(name: str, parent: int) -> Iterator[int]:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=parent)
    except OSError as error:
        raise DirectorySetupError(f"{name} is not a plain directory: {error}") from None
    try:
        yield descriptor
    finally:
        os.close(descriptor)


def _lstat(parent: int, name: str) -> os.stat_result | None:
    try:
        return os.lstat(name, dir_fd=parent)
    except FileNotFoundError:
        return None


def _exists(parent: int, name: str) -> bool:
    return _lstat(parent, name) is not None


def _remove_tree_if_present(parent: int, name: str) -> None:
    """Delete `parent/name` whatever it is; a link is deleted, never followed."""
    entry = _lstat(parent, name)
    if entry is None:
        return
    if stat.S_ISDIR(entry.st_mode):
        # The descriptor-based walk: links inside are deleted, not followed.
        shutil.rmtree(name, dir_fd=parent)
    else:
        os.unlink(name, dir_fd=parent)


def _remove_contents(directory: Path) -> None:
    """Delete everything inside `directory`, as its owner (run in the plugin's helper)."""
    for entry in os.scandir(directory):
        path = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            # A plugin may have made one of its own directories unreadable.
            os.chmod(path, 0o700)
            _remove_contents(path)
            os.rmdir(path)
        else:
            os.unlink(path)
