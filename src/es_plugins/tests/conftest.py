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
# A plugins_db server to provision against: src/plugins_db/lab/run.sh starts one with the real
# init script and pg_hba.conf and sets these.
POSTGRES_VARIABLES = (
    "ES_PLUGINS_TEST_PG_HOST",
    "ES_PLUGINS_TEST_PG_PORT",
    "ES_PLUGINS_TEST_PG_ADMIN_PASSWORD",
)
HAS_POSTGRES = all(os.environ.get(name) for name in POSTGRES_VARIABLES)


def pytest_collection_modifyitems(config, items):
    for item in items:
        if "linux" in item.keywords and not IS_LINUX:
            item.add_marker(pytest.mark.skip(reason="needs Linux"))
        if "root" in item.keywords and not IS_ROOT:
            item.add_marker(
                pytest.mark.skip(reason="needs root on Linux (the node's container capabilities)")
            )
        if "postgres" in item.keywords and not HAS_POSTGRES:
            item.add_marker(
                pytest.mark.skip(reason="needs a plugins_db server (src/plugins_db/lab/run.sh)")
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
    # Stands in for the egress policy volume, mounted below a directory the image makes.
    egress_policy = tmp_path / "lib" / "es_plugins_egress" / "policy"
    egress_policy.mkdir(parents=True)
    return NodeLayout(
        data_root=tmp_path / "lib" / "es_plugins",
        run_root=tmp_path / "run" / "es_plugins",
        launcher_socket_directory=tmp_path / "run" / "es_launcher",
        egress_policy_directory=egress_policy,
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


@pytest.fixture
async def plugin_databases():
    """Makes the desired database of a new plugin; drops whatever was made for it afterwards."""
    from tests.plugin_databases import desired_database, drop_plugin_database, new_identifier

    made = []

    def make(identifier: str | None = None, **arguments):
        desired = desired_database(identifier or new_identifier(), **arguments)
        made.append(desired)
        return desired

    yield make
    # Newest first: a later plugin's database may refer to an earlier one's roles.
    for desired in reversed(made):
        await drop_plugin_database(desired)
