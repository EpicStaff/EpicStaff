import os
import stat
import sys
import tempfile
from pathlib import Path

import pytest

from es_plugins.launcher.directory_setup import DirectorySetup, Ownership
from es_plugins.layout import NodeLayout

IS_LINUX = sys.platform.startswith("linux")
IS_ROOT = IS_LINUX and os.geteuid() == 0


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "linux" in item.keywords and not IS_LINUX:
            item.add_marker(pytest.mark.skip(reason="needs Linux"))
        if "root" in item.keywords and not IS_ROOT:
            item.add_marker(
                pytest.mark.skip(reason="needs root on Linux (the node's container capabilities)")
            )


@pytest.fixture
def layout(tmp_path):
    if IS_ROOT:
        # pytest makes its directories 0700; a plugin UID must be able to pass through them.
        for directory in (tmp_path, *tmp_path.parents):
            if directory == Path(tempfile.gettempdir()):
                break
            directory.chmod(stat.S_IMODE(directory.stat().st_mode) | 0o011)
    (tmp_path / "lib").mkdir()
    (tmp_path / "run").mkdir()
    return NodeLayout(
        data_root=tmp_path / "lib" / "es_plugins",
        run_root=tmp_path / "run" / "es_plugins",
        launcher_socket_directory=tmp_path / "run" / "es_launcher",
    )


@pytest.fixture
def own_ownership():
    return Ownership(os.getuid(), os.getgid())


@pytest.fixture
def unprivileged_setup(layout, own_ownership):
    """The launcher's directory operations with every owner set to the test's own UID."""
    setup = DirectorySetup(
        layout, launcher=own_ownership, agent=own_ownership, plugin_gid=os.getgid()
    )
    setup.prepare_tree()
    return setup
