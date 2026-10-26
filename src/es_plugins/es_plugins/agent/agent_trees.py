"""Delete what the agent itself keeps for a plugin on the node's volume.

The agent owns these trees: `venvs/<id>/`, `logs/<id>/`, `agent/unpack/<id>/` and `backups/<id>/`.
Every entry is taken by name inside a directory opened without following links, so a link is
deleted, never followed out of the tree. A missing tree is fine.
"""

import os
import shutil
import stat
from pathlib import Path

from es_plugins.layout import NodeLayout, check_version_segment

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def delete_agent_trees(layout: NodeLayout, plugin: str) -> None:
    """Everything the agent keeps for a plugin that is being removed. Runs in a thread."""
    empty_directory(layout.plugin_venvs(plugin))
    for tree in (
        layout.plugin_logs(plugin),
        layout.unpack_directory / plugin,
        layout.plugin_backups(plugin),
    ):
        delete_entry(tree.parent, tree.name)


def prune_agent_trees(layout: NodeLayout, plugin: str, keep_version: str) -> list[str]:
    """Delete every venv of the plugin but `keep_version`'s, and its unpacked packages.

    Returns the venv names deleted. Runs in a thread.
    """
    check_version_segment(keep_version)
    venvs = layout.plugin_venvs(plugin)
    try:
        names = os.listdir(venvs)
    except FileNotFoundError:
        names = []
    removed = sorted(name for name in names if name != keep_version)
    for name in removed:
        delete_entry(venvs, name)
    delete_entry(layout.unpack_directory, plugin)
    return removed


def empty_directory(directory: Path) -> None:
    """Delete everything in `directory`, keeping it; anything but a directory there is left to the
    launcher, which removes the entry itself."""
    try:
        entry = os.lstat(directory)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(entry.st_mode):
        return
    # O_NOFOLLOW: a link swapped in since the check is refused, not followed.
    descriptor = os.open(directory, _DIRECTORY_FLAGS)
    try:
        for name in os.listdir(descriptor):
            _delete_in(descriptor, name)
    finally:
        os.close(descriptor)


def delete_entry(parent: Path, name: str) -> None:
    try:
        descriptor = os.open(parent, _DIRECTORY_FLAGS)
    except FileNotFoundError:
        return
    try:
        _delete_in(descriptor, name)
    finally:
        os.close(descriptor)


def _delete_in(parent_descriptor: int, name: str) -> None:
    try:
        entry = os.lstat(name, dir_fd=parent_descriptor)
    except FileNotFoundError:
        return
    if stat.S_ISDIR(entry.st_mode):
        # The descriptor-based walk: links inside are deleted, not followed.
        shutil.rmtree(name, dir_fd=parent_descriptor)
    else:
        os.unlink(name, dir_fd=parent_descriptor)
