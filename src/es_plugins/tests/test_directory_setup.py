import os
import stat
import threading

import pytest

from es_plugins.launcher import directory_setup
from es_plugins.launcher.directory_setup import DirectorySetup, DirectorySetupError, Ownership
from es_plugins.layout import AGENT_UID

PLUGIN = "weather"
PLUGIN_UID = 20001


def mode_of(path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def node_wide_modes(layout):
    return {
        layout.data_root: 0o755,
        layout.agent_directory: 0o750,
        layout.plugin_data_root: 0o711,
        layout.plugins_root: 0o711,
        layout.venvs_root: 0o711,
        layout.logs_root: 0o700,
        layout.run_root: 0o711,
        layout.launcher_socket_directory: 0o750,
        layout.heartbeat_file: 0o644,
    }


def plugin_modes(layout):
    return {
        layout.plugin_home(PLUGIN): 0o700,
        layout.plugin_temporary_directory(PLUGIN): 0o700,
        layout.plugin_code_root(PLUGIN): 0o750,
        layout.plugin_venvs(PLUGIN): 0o750,
        layout.plugin_run_directory(PLUGIN): 0o711,
    }


def test_the_node_tree_gets_its_modes(layout, unprivileged_setup):
    assert {path: mode_of(path) for path in node_wide_modes(layout)} == node_wide_modes(layout)


def test_setup_repairs_an_existing_tree_whatever_modes_it_has(layout, unprivileged_setup):
    # Deepest first: a directory set to 0000 cannot be entered to change what is below it.
    for path in sorted(node_wide_modes(layout), key=lambda path: len(path.parts), reverse=True):
        os.chmod(path, 0o000 if path.is_dir() else 0o600)

    unprivileged_setup.prepare_tree()
    unprivileged_setup.prepare_tree()

    assert {path: mode_of(path) for path in node_wide_modes(layout)} == node_wide_modes(layout)


def test_a_plugins_directories_get_their_modes_and_setup_is_idempotent(
    layout, unprivileged_setup
):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    (layout.plugin_temporary_directory(PLUGIN) / "cache").write_text("kept")
    os.chmod(layout.plugin_temporary_directory(PLUGIN), 0o000)
    os.chmod(layout.plugin_home(PLUGIN), 0o500)

    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())

    assert {path: mode_of(path) for path in plugin_modes(layout)} == plugin_modes(layout)
    assert (layout.plugin_temporary_directory(PLUGIN) / "cache").read_text() == "kept"


def change_times(paths) -> dict:
    """Inode and change time: a chmod or chown, even to the same values, moves the change time."""
    return {path: (os.lstat(path).st_ino, os.lstat(path).st_ctime_ns) for path in paths}


def test_preparing_a_correct_tree_and_plugin_again_touches_nothing(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    paths = [path for path in node_wide_modes(layout) if path.is_dir()] + list(plugin_modes(layout))
    before = change_times(paths)

    unprivileged_setup.prepare_tree()
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())

    # A running plugin's HOME is never taken back to root and handed over again.
    assert change_times(paths) == before


def test_a_link_planted_as_the_plugins_tmp_is_replaced_not_followed(
    tmp_path, layout, unprivileged_setup
):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o755)
    temporary = layout.plugin_temporary_directory(PLUGIN)
    temporary.rmdir()
    temporary.symlink_to(target)

    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())

    assert temporary.is_dir() and not temporary.is_symlink()
    assert mode_of(target) == 0o755


def test_a_link_in_place_of_a_node_directory_is_refused(tmp_path, layout, unprivileged_setup):
    target = tmp_path / "elsewhere"
    target.mkdir()
    layout.plugins_root.rmdir()
    layout.plugins_root.symlink_to(target)

    with pytest.raises(DirectorySetupError):
        unprivileged_setup.prepare_tree()


def unpack_source(layout, version="0.2.0"):
    source = layout.unpacked_source(PLUGIN, version)
    (source / "weather_plugin").mkdir(parents=True)
    (source / "weather_plugin" / "__init__.py").write_text("")
    (source / "weather_plugin" / "app.py").write_text("app = None\n")
    return source


def test_code_is_installed_as_read_only_files_and_directories(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    unpack_source(layout)

    unprivileged_setup.install_code(PLUGIN, "0.2.0")

    installed = layout.plugin_source(PLUGIN, "0.2.0")
    assert (installed / "weather_plugin" / "app.py").read_text() == "app = None\n"
    assert mode_of(installed / "weather_plugin" / "app.py") == 0o644
    assert mode_of(installed / "weather_plugin") == 0o755
    assert mode_of(layout.plugin_code(PLUGIN, "0.2.0")) == 0o755
    assert sorted(entry.name for entry in layout.plugin_code_root(PLUGIN).iterdir()) == ["0.2.0"]


def test_installing_a_version_again_replaces_it(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    unprivileged_setup.install_code(PLUGIN, "0.2.0")
    (source / "weather_plugin" / "app.py").write_text("app = 'new'\n")
    (source / "weather_plugin" / "__init__.py").unlink()

    unprivileged_setup.install_code(PLUGIN, "0.2.0")

    installed = layout.plugin_source(PLUGIN, "0.2.0") / "weather_plugin"
    assert sorted(entry.name for entry in installed.iterdir()) == ["app.py"]
    assert (installed / "app.py").read_text() == "app = 'new'\n"
    assert sorted(entry.name for entry in layout.plugin_code_root(PLUGIN).iterdir()) == ["0.2.0"]


def test_a_link_inside_the_unpacked_code_is_refused(tmp_path, layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    secret = tmp_path / "another-plugins-secret"
    secret.write_text("secret")
    (source / "weather_plugin" / "stolen.py").symlink_to(secret)

    with pytest.raises(DirectorySetupError, match="stolen.py"):
        unprivileged_setup.install_code(PLUGIN, "0.2.0")

    assert not layout.plugin_code(PLUGIN, "0.2.0").exists()


def test_a_fifo_in_the_unpacked_code_is_refused(layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    os.mkfifo(source / "weather_plugin" / "pipe.py")

    with pytest.raises(DirectorySetupError, match="pipe.py is neither a regular file"):
        unprivileged_setup.install_code(PLUGIN, "0.2.0")


def test_a_fifo_swapped_in_after_the_check_is_refused_without_blocking(
    layout, unprivileged_setup, monkeypatch
):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    source = unpack_source(layout)
    os.mkfifo(source / "weather_plugin" / "pipe.py")
    real_lstat = os.lstat

    def lstat_seeing_a_file(name, *arguments, **options):
        # The agent replaced a regular file by a FIFO between the launcher's lstat and open.
        if name == "pipe.py":
            regular = list(real_lstat(source / "weather_plugin" / "app.py"))
            return os.stat_result(regular)
        return real_lstat(name, *arguments, **options)

    monkeypatch.setattr(directory_setup.os, "lstat", lstat_seeing_a_file)
    outcome = []

    def install():
        try:
            unprivileged_setup.install_code(PLUGIN, "0.2.0")
        except DirectorySetupError as error:
            outcome.append(str(error))

    # A blocking open of a FIFO with no writer would never return: run it where it can hang.
    installing = threading.Thread(target=install, daemon=True)
    installing.start()
    installing.join(5)

    assert not installing.is_alive(), "the launcher blocked opening a FIFO"
    assert outcome and "pipe.py is not a regular file" in outcome[0]


def test_a_link_in_the_path_to_the_unpacked_code_is_refused(tmp_path, layout, unprivileged_setup):
    unprivileged_setup.prepare_plugin(PLUGIN, os.getuid())
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "0.2.0" / "backend" / "src").mkdir(parents=True)
    (elsewhere / "0.2.0" / "backend" / "src" / "other.py").write_text("other plugin code")
    layout.unpack_directory.mkdir(parents=True)
    (layout.unpack_directory / PLUGIN).symlink_to(elsewhere)

    with pytest.raises(DirectorySetupError):
        unprivileged_setup.install_code(PLUGIN, "0.2.0")


@pytest.mark.parametrize("version", ["..", "../other", "0.2.0/../x", ".hidden"])
def test_a_version_that_is_not_one_path_segment_is_refused(layout, unprivileged_setup, version):
    with pytest.raises(ValueError):
        unprivileged_setup.install_code(PLUGIN, version)


@pytest.mark.root
def test_root_gives_every_directory_its_owner(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin(PLUGIN, PLUGIN_UID)

    owners = {
        layout.data_root: (0, 0),
        layout.agent_directory: (AGENT_UID, 0),
        layout.logs_root: (AGENT_UID, AGENT_UID),
        layout.launcher_socket_directory: (0, AGENT_UID),
        layout.heartbeat_file: (AGENT_UID, AGENT_UID),
        layout.plugin_home(PLUGIN): (PLUGIN_UID, PLUGIN_UID),
        layout.plugin_temporary_directory(PLUGIN): (PLUGIN_UID, PLUGIN_UID),
        layout.plugin_code_root(PLUGIN): (0, PLUGIN_UID),
        layout.plugin_venvs(PLUGIN): (AGENT_UID, PLUGIN_UID),
        layout.plugin_run_directory(PLUGIN): (0, 0),
    }
    assert {path: (os.lstat(path).st_uid, os.lstat(path).st_gid) for path in owners} == owners


@pytest.mark.root
def test_purging_empties_the_home_as_the_plugin_and_removes_it(layout):
    setup = DirectorySetup(layout)
    setup.prepare_tree()
    setup.prepare_plugin(PLUGIN, PLUGIN_UID)
    nested = layout.plugin_home(PLUGIN) / "state" / "deep"
    nested.mkdir(parents=True)
    (nested / "data.db").write_text("x")
    for path in (layout.plugin_home(PLUGIN) / "state", nested, nested / "data.db"):
        os.chown(path, PLUGIN_UID, PLUGIN_UID)
    os.chmod(nested, 0o500)

    setup.purge_plugin_data(PLUGIN, PLUGIN_UID)

    assert not layout.plugin_home(PLUGIN).exists()


def test_a_test_setup_owns_everything_itself(own_ownership):
    assert own_ownership == Ownership(os.getuid(), os.getgid())
